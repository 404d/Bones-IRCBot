# -*- encoding: utf-8 -*-
from ConfigParser import SafeConfigParser


class BaseConfiguration(object):
    """
    Global configuration instance.
    """
    def __init__(self, file):
        self._conf = SafeConfigParser()
        self._conf.read(file)

    def get(self, section, option, server=None, default=None):
        keys = (server, section)
        if server and self._conf.has_section("server.%s.%s" % keys):
            if self._conf.has_option("server.%s.%s" % keys, option):
                return self._conf.get("server.%s.%s" % keys, option)
        if self._conf.has_section(section):
            if self._conf.has_option(section, option):
                return self._conf.get(section, option)
        return default

    def rehash(self):
        self._conf.read(file)

    def server(self, server):
        return ServerConfiguration(server, self)


class ServerConfiguration(object):
    """
    Server configuration instance. Makes a copy of the global configuration
    and limits it to the scope of this server; overrides gets expanded
    and replaces their parent options. This gets passed to bot factories and
    subsequently to modules.
    """
    def __init__(self, server, configuration):
        self.config = configuration
        self.server = server
        self.data = {}
        self.load()

    def load(self):
        queue = []
        sections = self.config._conf.sections()

        self.load_global_config(sections, queue)
        self.load_server_config(queue)

    def load_global_config(self, sections, queue):
        for section in sections:
            try:
                self.data[section.lower()]
            except KeyError:
                self.data[section.lower()] = {}
            if section.lower().startswith("server."):
                tmp = section.split(".")
                if self.server and tmp[1] == self.server:
                    queue.append(section)
            else:
                for data in self.config._conf._sections[section]:
                    if not data == "__name__":
                        self.data[section.lower()][data] = self.config \
                            ._conf._sections[section][data]

    def load_server_config(self, queue):
        for section in queue:
            tmp = section.split(".")
            if len(tmp) > 2:
                stmp = ".".join(tmp[2:]).lower()
            elif section.lower() == ("server.%s" % self.server).lower():
                stmp = "server"
            else:
                stmp = section.lower()
            try:
                self.data[stmp]
            except KeyError:
                self.data[stmp] = {}
            for data in self.config._conf._sections[section]:
                if not data == "__name__":
                    self.data[stmp][data] = self.config._conf \
                        ._sections[section][data.lower()]

    def get(self, section, option, default=Exception):
        """Gets a configuration value from the current bot factory's configuration set.

        :param section: Name of the section that the option is defined in.
        :type section: String
        :param option: Name of the option to get.
        :type option: String
        :param default: Value to be returned if no such option could be found.
            :code:`default=Exception` results in a compatibility mode with
            older modules which basically works as an override for the new
            behaviour, resulting in option retrieval even if there's no such
            option.
        """
        if (section.lower() in self.data and
                option.lower() in self.data[section.lower()]) or \
                default is Exception:
            return self.data[section.lower()][option.lower()]
        else:
            return default
