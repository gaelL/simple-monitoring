#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Author: Gaël Lambert (gaelL) <gael.lambert@netwiki.fr>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import requests
import time
import logging
from os.path import isfile
from os.path import join as os_join
import os
from yaml import safe_load as load_yaml
import argparse
from queue import Empty
from multiprocessing import Process, Queue, current_process, freeze_support
from multiprocessing.sharedctypes import Value
from scheduler import Job
import signal
import sys
from prometheus_client import start_http_server, Summary, Counter
import random
import time

import boto3
from botocore.exceptions import ClientError
import os

import hvac

NUMBER_OF_CHECKS = Counter('number_checks', 'Description of counter')
HTTP_REQUESTS_DURATION = Summary('request_latency_seconds', 'HTTP requests', ['url_name'])
S3_REQUESTS_DURATION = Summary('s3_request_latency_seconds', 'S3 requests', ['bucket_name', 'type'])
VAULT_REQUESTS_DURATION = Summary('vault_request_latency_seconds', 'vault requests', ['name', 'type'])



LOG = logging.getLogger('metrics')

def init_logger(verbose=False):
    "Init logger and handler"
    if verbose:
        LOG.setLevel(logging.DEBUG)
    else:
        LOG.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s %(levelname)s -: %(message)s')
    hdl = logging.StreamHandler(); hdl.setFormatter(formatter); LOG.addHandler(hdl)

def get_args():
    "Init and return args from argparse"
    parser = argparse.ArgumentParser()

    parser.add_argument("-f", "--config-file",
            help="Config file.: ex conf.yaml.sample",
            type=open,
            required=True)

    parser.add_argument("--fetch",
            help="Start fetch metrics",
            action='store_true',
            default=False
            )

    parser.add_argument("-v", "--verbose",
            help="Run in verbose mode",
            action='store_true',
            default=False
            )

    return parser.parse_args()

#
# HTTP checks
#

def check_http(url):
    "Return date when request start. And latency time"
    start = time.time()
    local_time = time.localtime(start)
    date_format = time.strftime('%Y-%m-%d %H:%M:%S', local_time)
    try:
        requests.get(url)
    except requests.ConnectionError as e:
        LOG.warning('Unable to curl %s : %s' % (url, e))
        return date_format, ''
    return date_format, time.time() - start

#
# S3 checks
#

def s3_upload_file(s3_client ,file_name, file_size, bucket, object_name=None):
    start = time.time()
    if object_name is None:
        object_name = os.path.basename(file_name)

    with open(file_name, "wb") as out:
        out.truncate((1024**1)*file_size) # Generate Ko size into octets

    try:
        response = s3_client.upload_file(file_name, bucket, object_name)
    except ClientError as e:
        LOG.error(e)
        return False, time.time() - start
    return True, time.time() - start

def s3_download_file(s3_client ,file_name, bucket, object_name=None):
    start = time.time()
    if object_name is None:
        object_name = os.path.basename(file_name)

    try:
        response = s3_client.download_file(bucket, object_name, file_name)
    except ClientError as e:
        LOG.error(e)
        return False, time.time() - start
    return True, time.time() - start

def s3_delete_file(s3_client, bucket, object_name):
    start = time.time()
    try:
        response = s3_client.delete_object(Bucket=bucket, Key=object_name)
    except ClientError as e:
        LOG.error(e)
        return False, time.time() - start
    return True, time.time() - start

def check_s3(config):
    start = time.time()
    
    endpoint=config['endpoint']
    access_key=config['access_key']
    secret_key=config['secret_key']
    region=config['region']

    s3_client = boto3.client('s3', region_name=region,  endpoint_url=endpoint, aws_access_key_id=access_key, aws_secret_access_key=secret_key)

    u_status, upload_time = s3_upload_file(s3_client=s3_client,
                   file_name='/tmp/smk-s3-upload-%s' % config['name'],
                   file_size=config.get('file_size', 100),
                   bucket=config['name'],
                   object_name=config.get('key', 'smoke-test-%s' % config['name']))

    d_status, download_time = s3_download_file(s3_client=s3_client,
                   file_name='/tmp/smk-s3-download-%s' % config['name'],
                   bucket=config['name'],
                   object_name=config.get('key', 'smoke-test-%s' % config['name']))

    del_status, delete_time = s3_delete_file(s3_client=s3_client,
                   bucket=config['name'],
                   object_name=config.get('key', 'smoke-test-%s' % config['name']))
    full_time = time.time() - start

    result = {
        'full_time': full_time,
        'upload':   {'time': upload_time,   'status': u_status},
        'download': {'time': download_time, 'status': d_status},
        'delete':   {'time': delete_time,   'status': del_status},
    }
    return result

#
# Vault checks
#

def vault_write(vault_client, key):
    start = time.time()
    try:
        response = vault_client.write(
            path=key,
            secret=dict(foo='bar'),
        )
    except Exception as e:
        LOG.error(e)
        return False, time.time() - start
    return True, time.time() - start

def vault_read(vault_client, key):
    start = time.time()
    try:
        response = vault_client.read(path=key)
    except Exception as e:
        LOG.error(e)
        return False, time.time() - start
    return True, time.time() - start

def vault_delete(vault_client, key):
    start = time.time()
    try:
        response = vault_client.delete(path=key)
    except Exception as e:
        LOG.error(e)
        return False, time.time() - start
    return True, time.time() - start

def check_vault(config):
    start = time.time()
    
    endpoint=config['url']
    role_id=config['role_id']
    secret_id=config['secret_id']

    c_status = True
    try:
        vault_client = hvac.Client(
            url=endpoint,
        )
        tok = vault_client.auth.approle.login(
            role_id=role_id,
            secret_id=secret_id,
        )
    except Exception as e:
        LOG.error("Unable to connect to vault %s" % endpoint)
        LOG.error(e)
        c_status = False
    connect_time = time.time() - start

    w_status, write_time = vault_write(vault_client=vault_client, key=config['key'])
    r_status, read_time = vault_read(vault_client=vault_client, key=config['key'])
    d_status, delete_time = vault_delete(vault_client=vault_client, key=config['key'])

    full_time = time.time() - start

    result = {
        'full_time': full_time,
        'connect':   {'time': connect_time,   'status': c_status},
        'write':     {'time': write_time,     'status': w_status},
        'read':      {'time': read_time,      'status': r_status},
        'delete':    {'time': delete_time,    'status': d_status},
    }
    return result

#
# Core code
#

def worker(stop_process, result_queue, global_config, local_config, wtype):
    """Just fetch url every fetch_periode"""

    # Disable ctrl + c
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    if wtype is None:
        LOG.error("Worker type None: %s" % local_config)
        return

    # HTTP
    if wtype == "http":
        url = local_config.get('url')
        label = local_config.get('label')
        fetch_period = local_config.get('fetch_period', global_config['default_fetch_period'])
        job = Job(name=label,
                  every=fetch_period,
                  func=check_http,
                  func_args={'url':url})
    # S3
    elif wtype == "s3":
        label = local_config.get('name')
        fetch_period = local_config.get('fetch_period', global_config['default_fetch_period'])
        job = Job(name=label,
                  every=fetch_period,
                  func=check_s3,
                  func_args={'config': local_config})

    # vault
    elif wtype == "vault":
        label = local_config.get('name')
        fetch_period = local_config.get('fetch_period', global_config['default_fetch_period'])
        job = Job(name=label,
                  every=fetch_period,
                  func=check_vault,
                  func_args={'config': local_config})

    LOG.info('worker - Start worker %s' % label)
    while stop_process.value != 1:
        # If scheduled curl go or do nothing
        if job.should_run():
            LOG.info('worker - run %s' % label)
            job_result = job.run()
            
            result_queue.put({'job_result': job_result, 'local_config': local_config, 'wtype': wtype})
        time.sleep(0.1)


def consumer(stop_process, result_queue, config):
    "Consume results from workers. And write them in csv files"
    # Disable ctrl + c
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    # Start up the server to expose the metrics.
    start_http_server(8000)

    # Get and print results
    LOG.info('consumer - Start consumer')
    while stop_process.value != 1:
        try:
            msg = result_queue.get_nowait()
            LOG.debug('consumer - Receved ->>> %s\n' % str(msg))
            NUMBER_OF_CHECKS.inc()
            record = msg['job_result']
            local_config = msg['local_config']

            if record is None: continue

            if msg.get("wtype") is None:
                LOG.warning("consumer - get none type, ignoring message")
                continue
            elif msg.get("wtype") == "http":
                label = local_config['label']
                HTTP_REQUESTS_DURATION.labels(url_name=label).observe(record[1])
            elif msg.get("wtype") == "s3":
                bucket_name = local_config['name']
                S3_REQUESTS_DURATION.labels(bucket_name=bucket_name, type="upload").observe(record['upload']['time'])
                S3_REQUESTS_DURATION.labels(bucket_name=bucket_name, type="download").observe(record['download']['time'])
                S3_REQUESTS_DURATION.labels(bucket_name=bucket_name, type="delete").observe(record['delete']['time'])
                S3_REQUESTS_DURATION.labels(bucket_name=bucket_name, type="full").observe(record['full_time'])
            elif msg.get("wtype") == "vault":
                name = local_config['name']
                VAULT_REQUESTS_DURATION.labels(name=name, type="write").observe(record['write']['time'])
                VAULT_REQUESTS_DURATION.labels(name=name, type="connect").observe(record['connect']['time'])
                VAULT_REQUESTS_DURATION.labels(name=name, type="read").observe(record['read']['time'])
                VAULT_REQUESTS_DURATION.labels(name=name, type="delete").observe(record['delete']['time'])
                VAULT_REQUESTS_DURATION.labels(name=name, type="full").observe(record['full_time'])
        except Empty:
            # Write consumer ticks
            #sys.stdout.write('.')
            #sys.stdout.flush()
            time.sleep(config.get('consumer_frequency', 0.1))

def start_fetch(config):
    """Launch workers and consumer.
         * Workers : one by url. The worker fetch a url and return fetch time
         * consumer : Just one. Get datas returned by workers
                      and write them to csv files"""

    # Create queues
    result_queue = Queue() # for results
    stop_process = Value('i', 0) # Integer shared value

    # Start HTTP checks fetch all urls
    for url_config in config.get('urls', []):
        # Launch workers : process who fetch website and push result in result_queue
        Process(target=worker, args=(stop_process, result_queue, config, url_config, "http")).start()

    # Start S3 checks
    for s3_config in config.get('s3_buckets', []):
        # Launch workers : process who fetch website and push result in result_queue
        Process(target=worker, args=(stop_process, result_queue, config, s3_config, "s3")).start()

    # Start Vault checks
    for vault_config in config.get('vault', []):
        # Launch workers : process who fetch website and push result in result_queue
        Process(target=worker, args=(stop_process, result_queue, config, vault_config, "vault")).start()

    # Launch consumer : process that write results from result_queue in csv files
    consumer_process = Process(target=consumer, args=(stop_process, result_queue, config))
    consumer_process.start()

    # run forever
    try:
        consumer_process.join()
        #while True:
        #    time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_process.value = 1


if __name__ == '__main__':

    args = get_args()

    init_logger(verbose=args.verbose)

    # Load config
    config = load_yaml(args.config_file)

    if args.fetch:
        start_fetch(config)
