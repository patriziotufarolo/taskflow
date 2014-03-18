# -*- coding: utf-8 -*-

# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright (C) 2013 Rackspace Hosting Inc. All Rights Reserved.
#    Copyright (C) 2013 Yahoo! Inc. All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import abc
import logging

import six

from taskflow import atom
from taskflow import exceptions as exc

LOG = logging.getLogger(__name__)

# Retry actions
REVERT = "REVERT"
REVERT_ALL = "REVERT_ALL"
RETRY = "RETRY"


@six.add_metaclass(abc.ABCMeta)
class Retry(atom.Atom):
    """A base class for retry that controls subflow execution.
       Retry can be executed multiple times and reverted. On subflow
       failure it makes a decision about what should be done with the flow
       (retry, revert to the previous retry, revert the whole flow, etc.).
    """

    default_provides = None

    def __init__(self, name=None, provides=None, requires=None,
                 auto_extract=True, rebind=None):
        if provides is None:
            provides = self.default_provides
        super(Retry, self).__init__(name, provides)
        self._build_arg_mapping(self.execute, requires, rebind, auto_extract,
                                ignore_list=['history'])

    @property
    def name(self):
        return self._name

    def set_name(self, name):
        self._name = name

    @abc.abstractmethod
    def execute(self, history, *args, **kwargs):
        """Activate a given retry which will produce data required to
           start or restart a subflow using previously provided values and a
           history of subflow failures from previous runs.
           Retry can provide same values multiple times (after each run),
           the latest value will be used by tasks. Old values will be saved to
           the history of retry that is a list of tuples (result, failures)
           where failures is a dictionary of failures by task names.
           This allows to make retries of subflow with different parameters.
        """

    def revert(self, history, *args, **kwargs):
        """Revert this retry using the given context, all results
           that had been provided by previous tries and all errors caused
           a reversion. This method will be called only if a subflow must be
           reverted without the retry. It won't be called on subflow retry, but
           all subflow's tasks will be reverted before the retry.
        """

    @abc.abstractmethod
    def on_failure(self, history, *args, **kwargs):
        """On subflow failure makes a decision about the future flow
           execution using information about all previous failures.
           Returns retry action constant:
           'RETRY' when subflow must be reverted and restarted again (maybe
           with new parameters).
           'REVERT' when this subflow must be completely reverted and parent
           subflow should make a decision about the flow execution.
           'REVERT_ALL' in a case when the whole flow must be reverted and
           marked as FAILURE.
        """


class AlwaysRevert(Retry):
    """Retry that always reverts subflow."""

    def on_failure(self, *args, **kwargs):
        return REVERT

    def execute(self, *args, **kwargs):
        pass


class AlwaysRevertAll(Retry):
    """Retry that always reverts a whole flow."""

    def on_failure(self, **kwargs):
        return REVERT_ALL

    def execute(self, **kwargs):
        pass


class Times(Retry):
    """Retries subflow given number of times. Returns attempt number."""

    def __init__(self, attempts=1, name=None, provides=None, requires=None,
                 auto_extract=True, rebind=None):
        super(Times, self).__init__(name, provides, requires,
                                    auto_extract, rebind)
        self._attempts = attempts

    def on_failure(self, history, *args, **kwargs):
        if len(history) < self._attempts:
            return RETRY
        return REVERT

    def execute(self, history, *args, **kwargs):
        return len(history)+1


class ForEachBase(Retry):
    """Base class for retries that iterate given collection."""

    def _get_next_value(self, values, history):
        values = list(values)  # copy it
        for (item, failures) in history:
            try:
                values.remove(item)  # remove exactly one element from item
            except ValueError:
                # one of the results is not in our list now -- who cares?
                pass
        if not values:
            raise exc.NotFound("No elements left in collection of iterable "
                               "retry controller %s" % self.name)
        return values[0]

    def _on_failure(self, values, history):
        try:
            self._get_next_value(values, history)
        except exc.NotFound:
            return REVERT
        else:
            return RETRY


class ForEach(ForEachBase):
    """Accepts a collection of values to the constructor. Returns the next
    element of the collection on each try.
    """

    def __init__(self, values, name=None, provides=None, requires=None,
                 auto_extract=True, rebind=None):
        super(ForEach, self).__init__(name, provides, requires,
                                      auto_extract, rebind)
        self._values = values

    def on_failure(self, history, *args, **kwargs):
        return self._on_failure(self._values, history)

    def execute(self, history, *args, **kwargs):
        return self._get_next_value(self._values, history)


class ParameterizedForEach(ForEachBase):
    """Accepts a collection of values from storage as a parameter of execute
     method. Returns the next element of the collection on each try.
    """

    def on_failure(self, values, history, *args, **kwargs):
        return self._on_failure(values, history)

    def execute(self, values, history, *args, **kwargs):
        return self._get_next_value(values, history)
