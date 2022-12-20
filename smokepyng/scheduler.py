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

import re
import time

# Usage :
# def fetch_http(num):
#     print num
# 
# func_args = {'num':1}
# 
# job = Job(name='test', every='10s', func=fetch_http, func_args=func_args)
# 
# if job.should_run():
#     job.run()

#https://github.com/dbader/schedule/blob/master/schedule/__init__.py

#class Scheduler(object):
#    def should_run(self):
#        """True if the job should be run now."""
#        return datetime.datetime.now() >= self.next_run
#    def run_pending():
#        pass
#    def _schedule_next_run(self):
#        pass


class Job(object):
    """Describ job name and time to run """

    def __init__(self, name, every, func, func_args):
        """
        parameters:
          every : could be in sec or min. example : 10sec or 1min
        """
        self.name = name
        self.func = func
        self.func_args = func_args
        self.next_run = 0

        # Convert every in seconds
        self.every = self._convert_in_sec(every)


    def _convert_in_sec(self, time_str):
        "Convert string in sec like 10s = 10"
        regex = re.match('([0-9]+)s$', time_str)
        if regex is not None:
            return float(regex.group(1))
        else:
            raise Exception('Job time seems not in a valid format.')


    def should_run(self):
        """True if the job should be run now."""
        return int(time.time()) >= self.next_run

    def run(self):
        "Run the job function and schedule next run"
        now = int(time.time())
        self._schedule_next_run(last_run=now)
        return self.func(**self.func_args)

    def _schedule_next_run(self, last_run):
        "Set the timestamp for the next job"
        self.next_run = last_run + self.every



