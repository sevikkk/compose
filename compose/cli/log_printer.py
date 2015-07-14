from __future__ import unicode_literals
from __future__ import absolute_import
import sys

from itertools import cycle, repeat
from compose.container import Container

from .multiplexer import Multiplexer, STOP
from . import colors
from .utils import split_buffer
from ..const import LABEL_PROJECT


class LogPrinter(object):
    def __init__(self, containers, attach_params=None, output=sys.stdout, monochrome=False, follow=False, project=None):
        self.containers = containers
        self.attach_params = attach_params or {}
        self.prefix_width = self._calculate_prefix_width(containers)
        self.generators = self._make_log_generators(monochrome, follow, project)
        self.output = output
        self.follow = follow
        self.monochrome = monochrome
        self.mux = None

    def run(self):
        self.mux = Multiplexer(self.generators, follow=self.follow)
        for line in self.mux.loop():
            self.output.write(line)

    def _calculate_prefix_width(self, containers):
        """
        Calculate the maximum width of container names so we can make the log
        prefixes line up like so:

        db_1  | Listening
        web_1 | Listening
        """
        prefix_width = 0
        for container in containers:
            prefix_width = max(prefix_width, len(container.name_without_project))
        return prefix_width

    def _make_log_generators(self, monochrome, follow, project):
        if monochrome:
            def no_color(text):
                return text

            color_fns = repeat(no_color)
        else:
            color_fns = cycle(colors.rainbow())

        generators = []

        for container in self.containers:
            color_fn = next(color_fns)
            generators.append(self._make_log_generator(container, color_fn))

        if follow:
            color_fn = next(color_fns)
            generators.append(self._make_events_generator(project, color_fn, color_fns))

        return generators

    def _make_log_generator(self, container, color_fn):
        prefix = color_fn(self._generate_prefix(container)).encode('utf-8')
        # Attach to container before log printer starts running
        line_generator = split_buffer(self._attach(container), '\n')

        for line in line_generator:
            yield prefix + line

        exit_code = container.wait()
        yield prefix + color_fn("%s exited with code %s\n" % (container.name, exit_code))
        yield STOP

    def _make_events_generator(self, project, color_fn, color_fns):
        class FakeContainer(object):
            name_without_project = "events"

        prefix = color_fn(self._generate_prefix(FakeContainer())).encode('utf-8')
        # Attach to container before log printer starts running
        events_generator = project.client.events(decode=True)

        for event in events_generator:
            status = event.get("status")
            container_id = event.get("id")
            if status in ('start',):
                container = Container.from_id(project.client, container_id)
                proj_name = container.labels.get(LABEL_PROJECT)
                if proj_name == project.name:
                    color_fn = next(color_fns)
                    new_gen = self._make_log_generator(container, color_fn)
                    self.mux.add_reader(new_gen)

            yield prefix + `event` + '\n'

    def _generate_prefix(self, container):
        """
        Generate the prefix for a log line without colour
        """
        name = container.name_without_project
        padding = ' ' * (self.prefix_width - len(name))
        return ''.join([name, padding, ' | '])

    def _attach(self, container):
        params = {
            'stdout': True,
            'stderr': True,
            'stream': True,
        }
        params.update(self.attach_params)
        params = dict((name, 1 if value else 0) for (name, value) in list(params.items()))
        return container.attach(**params)
