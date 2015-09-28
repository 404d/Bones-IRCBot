# -*- encoding: utf8 -*-
import re
import logging
import logging.config
import urllib2

from twisted.words.protocols import irc
from twisted.internet import defer, protocol, reactor

import bones.event

logging.addLevelName(2, "RAW")
log = logging.getLogger(__name__)
log.raw = lambda *args: log.log(2, *args)


def removeEmptyElementsFromList(l):
    return [e for e in l if e]


class InvalidBonesModuleException(Exception):
    pass


class InvalidConfigurationException(Exception):
    pass


class NoSuchBonesModuleException(Exception):
    pass


class BonesModuleAlreadyLoadedException(Exception):
    pass


class BonesBot(irc.IRCClient):
    def __init__(self, *args, **kwargs):
        self.channels = {}
        self.users = {}
        # Prepare some server implementation details, to be filled out later
        # from ISUPPORT options.
        self.channel_types = "#"
        self.channel_modes = {
            "list": [],
            "always": [],
            "set": [],
            "never": [],
        }
        self.prefixes = [("o", "@"), ("v", "+")]

    def get_channel(self, name):
        """Returns the Channel object for the given channel."""
        if name not in self.channels:
            self.channels[name] = bones.event.Channel(name, self)
        return self.channels[name]

    def get_user(self, target):
        """Returns the User object for the given target if it exists, None if
        otherwise."""
        if "!" in target:
            name = target.split("!")[0]
            semiMask = target.split("!")[1].split("@")
        else:
            name = target
            semiMask = None
        if name not in self.users:
            self.users[name] = bones.event.User(target, self)
        elif semiMask:
            self.users[name].username = semiMask[0]
            self.users[name].hostname = semiMask[1]
        return self.users[name]

    def create_user(self, target):
        """Prepares a User object for the given target."""
        if "!" in target:
            name = target.split("!")[0]
        else:
            name = target
        if name not in self.users:
            self.users[name] = bones.event.User(target, self)
        else:
            error = "Could not create user \"{}\": user already exists"
            raise Exception(error.format(target))
        return self.users[name]

    def remove_channel(self, name):
        # TODO: Remove the channel from all user instances.
        if name not in self.channels:
            return
        channel = self.channels[name]
        for user in channel.users:
            user.channels.remove(channel)
        del self.channels[name]

    def _get_nickname(self):
        return self.factory.nickname
    nickname = property(_get_nickname)

    def _get_realname(self):
        return self.factory.realname
    realname = property(_get_realname)

    def _get_username(self):
        return self.factory.username
    username = property(_get_username)

    def _get_versionName(self):
        return self.factory.versionName
    versionName = property(_get_versionName)

    def _get_versionNum(self):
        return self.factory.versionNum
    versionNum = property(_get_versionNum)

    def _get_versionEnv(self):
        return self.factory.versionEnv
    versionEnv = property(_get_versionEnv)

    def _get_sourceURL(self):
        return self.factory.sourceURL
    sourceURL = property(_get_sourceURL)

    def _get_tag(self):
        return self.factory.tag
    tag = property(_get_tag)

    def signedOn(self):
        """Event called when the bot receives a registration confirmation from
        the server"""
        # We've connected to the server, reset this so that when we disconnect
        # we'll immediately try to reconnect.
        self.factory.reconnectAttempts = 0

        # InspIRCd mode that shows "user :is a bot" in whois.
        if self.factory.settings.get("server", "setBot", default="false") \
                == "true":
            self.mode(self.nickname, True, "B")

        event = bones.event.BotSignedOnEvent(self)
        bones.event.fire(self.tag, event)
        log.info("Signed on as %s.", self.nickname)

        # Join all the channels defined in our config.
        for channel in self.factory.channels:
            self.join(channel)

    def created(self, when):
        log.debug(
            "Received server creation info: %s",
            when
        )
        event = bones.event.ServerCreatedEvent(self, when)
        bones.event.fire(self.tag, event)

    def yourHost(self, info):
        log.debug(
            "Received server host info: %s",
            info
        )
        event = bones.event.ServerHostInfoEvent(self, info)
        bones.event.fire(self.tag, event)

    def myInfo(self, servername, version, umodes, cmodes):
        log.debug(
            "Received server info from %s: Version %s, Usermodes %s, "
            "Channelmodes %s",

            servername, version, umodes, cmodes
        )
        event = bones.event.ServerInfoEvent(
            self, servername, version, umodes, cmodes
        )
        bones.event.fire(self.tag, event)

    def luserClient(self, info):
        log.debug(
            "Received client info from server: %s",
            info
        )
        event = bones.event.ServerClientInfoEvent(self, info)
        bones.event.fire(self.tag, event)

    def bounce(self, info):
        log.debug(
            "Received bounce info: %s",
            info
        )
        event = bones.event.BounceEvent(self, info)
        bones.event.fire(self.tag, event)

    def isupport(self, options):
        for option in options:
            if option.startswith("PREFIX=("):
                data = option[len("PREFIX=("):]
                data = data.split(")")
                self.prefixes = zip(data[0], data[1])
                log.debug("Server prefixes: %s" % self.prefixes)

            elif option.startswith("CHANMODES="):
                data = option[len("CHANMODES="):]
                data = data.split(",")
                self.channel_modes["list"] = data[0]
                self.channel_modes["always"] = data[1]
                self.channel_modes["set"] = data[2]
                self.channel_modes["never"] = data[3]
                log.debug("Server channel modes: %s" % self.channel_modes)

            elif option.startswith("CHANTYPES="):
                self.channel_types = option[len("CHANTYPES="):]

        event = bones.event.ServerSupportEvent(self, options)
        bones.event.fire(self.tag, event)

    def luserChannels(self, channels):
        log.debug(
            "This server have %s channels",
            channels
        )
        event = bones.event.ServerChannelCountEvent(self, channels)
        bones.event.fire(self.tag, event)

    def luserOp(self, ops):
        log.debug(
            "There's currently %s opered clients on this server",
            ops
        )
        event = bones.event.ServerOpCountEvent(self, ops)
        bones.event.fire(self.tag, event)

    def luserMe(self, info):
        log.debug(
            "Received local server info: %s",
            info
        )
        event = bones.event.ServerLocalInfoEvent(self, info)
        bones.event.fire(self.tag, event)

    def noticed(self, user, channel, message):
        event = bones.event.BotNoticeReceivedEvent(
            self, user, channel, message
        )
        bones.event.fire(self.tag, event)

    def modeChanged(self, user, target, set, modes, args):
        # TODO: Ditch this and override irc_MODE
        # TODO: This should be changed as a part of the interface for mode
        # changing we'll make at one point in time.
        if [True for x in self.channel_types if x is target[0]]:
            target = self.get_channel(target)
            args = [x for x in args if x is not None]
            target._set_modes(modes, args, set)
        event = bones.event.ModeChangedEvent(
            self, user, target, set, modes, args
        )
        bones.event.fire(self.tag, event)

    def kickedFrom(self, channelName, kicker, message):
        channel = self.get_channel(channelName)
        log.info(
            "Kicked from channel %s by %s. Reason: %s",
            channel, kicker, message
        )
        event = bones.event.BotKickedEvent(self, channel, kicker, message)
        bones.event.fire(self.tag, event)

    def nickChanged(self, nick):
        log.info(
            "Changed nick to %s",
            nick
        )
        # TODO: Update client's nickname field
        event = bones.event.BotNickChangedEvent(self, nick)
        bones.event.fire(self.tag, event)

    def userLeft(self, mask, channelName, partMessage):
        channel = self.get_channel(channelName)
        user = self.get_user(mask)
        if not user:
            user = self.create_user(mask)
        log.info(
            "User %s parted from %s",
            user, channel
        )

        def userPartCleanup(event):
            if event.user in event.channel.users:
                log.debug("Removing %s from %s", event.user, event.channel)
                event.channel.users.remove(event.user)
        event = bones.event.UserPartEvent(self, user, channel)
        bones.event.fire(self.tag, event, callback=userPartCleanup)

    def userQuit(self, mask, quitMessage):
        user = self.get_user(mask)
        if not user:
            user = self.create_user(mask)
        log.info(
            "User %s quit (Reason: %s)",
            user, quitMessage
        )

        def userQuitCleanup(event):
            for channelName in self.channels:
                channel = self.get_channel(channelName)
                if event.user in channel.users:
                    log.debug("Removing %s from %s", event.user, channel)
                    channel.users.remove(event.user)
            log.debug("Deleting %s", event.user)
            del event.user
        event = bones.event.UserQuitEvent(self, user, quitMessage)
        bones.event.fire(self.tag, event, callback=userQuitCleanup)

    def userKicked(self, kickeeNick, channelName, kickerNick, message):
        channel = self.get_channel(channelName)
        kickee = self.get_user(kickeeNick)
        if not kickee:
            kickee = self.create_user(kickeeNick)
        kicker = self.get_user(kickerNick)
        if not kicker:
            kicker = self.create_user(kickerNick)
        log.debug(
            "User %s was kicked from %s by %s (Reason: %s)",
            kickee, channel, kicker, message
        )

        def userKickedCleanup(event):
            if event.user in event.channel.users:
                event.channel.users.remove(event.user)
            if event.channel in event.user.channels:
                event.user.channels.remove(event.channel)
        event = bones.event.UserKickedEvent(
            self, kickee, channel, kicker, message
        )
        bones.event.fire(self.tag, event, userKickedCleanup)

    def action(self, user, channelName, data):
        channel = self.get_channel(channelName)
        user = self.get_user(user)
        log.debug(
            "User %s actioned in %s: %s",
            user, channel, data
        )
        event = bones.event.UserActionEvent(self, user, channel, data)
        bones.event.fire(self.tag, event)

    def irc_TOPIC(self, prefix, params):
        self.topicUpdated(prefix, params[0], params[1])

    def irc_RPL_TOPIC(self, prefix, params):
        self.topicUpdated(prefix, params[1], params[2])

    def irc_RPL_NOTOPIC(self, prefix, params):
        self.topicUpdated(prefix, params[1], "")

    def topicUpdated(self, hostmask, channelName, newTopic):
        channel = self.get_channel(channelName)
        user = self.get_user(hostmask)
        log.debug(
            "User %s changed topic of %s to %s",
            user, channel, newTopic
        )
        channel.topic = bones.event.Topic(newTopic, user)
        event = bones.event.ChannelTopicChangedEvent(
            self, user, channel, newTopic
        )
        bones.event.fire(self.tag, event)

    def userRenamed(self, oldname, newname):
        log.debug(
            "User %s changed nickname to %s",
            oldname, newname
        )
        user = self.get_user(oldname)
        if user:
            user.nickname = newname
            # Set the target name too. This is needed for user.msg and the like
            user.name = newname
            # Fix the prefix mode listings
            for channelname in self.channels:
                channel = self.channels[channelname]
                for (mode, prefix) in self.prefixes:
                    if mode in channel.modes and \
                            oldname in channel.modes[mode]:
                        channel.modes[mode].remove(oldname)
                        channel.modes[mode].add(newname)
                        log.debug("Mode refresh in %s: -%s+%s %s %s",
                                  channel, mode, mode, oldname, newname)
            self.users[newname] = user
            del self.users[oldname]
        else:
            user = self.create_user(newname)

        event = bones.event.UserNickChangedEvent(self, user, oldname, newname)
        bones.event.fire(self.tag, event)

    def receivedMOTD(self, motd):
        event = bones.event.ServerMOTDReceivedEvent(self, motd)
        bones.event.fire(self.tag, event)

    def joined(self, channelName):
        channel = self.get_channel(channelName)
        log.info(
            "Joined channel %s.",
            channel
        )
        if [True for t in self.channel_types if channel.name.startswith(t)]:
            self.sendLine("MODE %s" % channel.name)
        else:
            self.sendLine("MODE #%s" % channel.name)

        event = bones.event.BotJoinEvent(self, channel)
        bones.event.fire(self.tag, event)

    def join(self, channel):
        event = bones.event.BotPreJoinEvent(self, channel)

        def doJoin(thisEvent):
            if thisEvent.isCancelled is False:
                irc.IRCClient.join(thisEvent.client, thisEvent.channel)

        bones.event.fire(self.tag, event, callback=doJoin)

    def userJoined(self, mask, channel):
        channel = self.get_channel(channel)
        user = self.get_user(mask)
        if not user:
            user = self.create_user(mask)
        log.debug("Event userJoined: %s %s", user, channel)
        event = bones.event.UserJoinEvent(self, channel, user)
        user = event.user
        user.channels.append(channel)
        channel.users.append(user)
        bones.event.fire(self.tag, event)

    def irc_PRIVMSG(self, prefix, params):
        sender = self.get_user(prefix)
        if not sender:
            sender = self.create_user(prefix)
        # Determine whether this is in a query or a channel
        # This is simply done by checking whether the first char in
        # the source name is in the `self.channel_types` array.
        target = params[0]
        if target[0] in self.channel_types:
            target = self.get_channel(target)
            specificEvent = bones.event.ChannelMessageEvent
        else:
            target = self.get_user(prefix)
            if not target:
                target = self.create_user(prefix, self)
            specificEvent = bones.event.UserMessageEvent

        # Extract the message content from the protocol message.
        # As the message should be after ":", it should be contained in
        # the last index in params.
        msg = params[-1]
        # Let twisted handle CTCP queries
        if msg.startswith(irc.X_DELIM):
            data = irc.ctcpExtract(msg)
            if data['extended']:
                # Got CTCP query
                self.ctcpQuery(prefix, target.name, data['extended'])
                return
            elif not data['normal']:
                return
        log.debug("Message: %s %s: %s", sender, target, msg)
        # Send a IrcPrivmsgEvent for this event.
        event = bones.event.IrcPrivmsgEvent(self, sender, target, msg)
        bones.event.fire(self.tag, event)
        # Send a UserMessageEvent or ChannelMessageEvent for this event
        # depending on whether the target is a User or a Channel.
        event = specificEvent(self, sender, target, msg)
        bones.event.fire(self.tag, event)
        # Check if the message contains a trigger call.
        # TODO: Bail if UserMessageEvent
        data = self.factory.reCommand.match(msg.decode("utf-8"))
        if data:
            trigger = data.group(2)
            args = msg.split(" ")[1:]
            log.debug(
                "Received trigger %s%s.",
                data.group(1), trigger
            )
            triggerEvent = bones.event.TriggerEvent(
                self, user=sender, channel=target, msg=msg, args=args,
                match=data
            )
            bones.event.fire(self.tag, "<Trigger: %s>" % trigger.lower(),
                             triggerEvent)

    def pong(self, user, secs):
        log.debug(
            "CTCP pong: %fs from %s",
            secs, user
        )
        event = bones.event.CTCPPongEvent(self, user, secs)
        bones.event.fire(self.tag, event)

    def irc_RPL_CHANNELMODEIS(self, prefix, params):
        channel = params[1]
        modes = params[2]
        args = ""
        if len(params) >= 4:
            args = params[3:]
        log.debug("RPL_CHANNELMODEIS: %s %s %s", channel, modes, args)
        self.get_channel(channel)._set_modes(modes[1:], args, True)

    def irc_RPL_NAMREPLY(self, prefix, params):
        channel = self.get_channel(params[2])
        nicks = params[3].split(" ")
        modes = []
        args = []
        for nick in nicks:
            if nick:
                # TODO: Iterate over nickname until a character that isn't in
                # self.prefixes is found.
                mode = [m for m, p in self.prefixes if p == nick[0]]
                if mode:
                    nickname = nick[len(mode):]
                else:
                    nickname = nick
                user = self.get_user(nickname)
                if not user:
                    user = self.create_user(nickname)
                user.channels.append(channel)
                channel.users.append(user)
                if mode:
                    for prefixMode in mode:
                        modes.append(prefixMode)
                    args.append(nick[len(mode):])
                    user.nickname = nick[len(mode):]
                else:
                    user.nickname = nick
        if modes:
            channel._set_modes("".join(modes), args, True)

    def irc_INVITE(self, prefix, params):
        event = bones.event.BotInviteEvent(self, params[1],
                                           self.get_user(prefix))

        def onInviteJoin(event):
            if self.factory.settings.get("bot", "joinOnInvite",
                                         default="false") != "true":
                return
            if event.isCancelled:
                log.debug("Got invited to '%s' on {%s} by %s, but the event "
                          "was cancelled.", event.channel, self.tag,
                          event.inviter)
                return
            log.info(
                "Got invited to '%s' on {%s} by %s, joining.",
                event.channel, self.tag, event.inviter
            )
            self.join(event.channel)
        bones.event.fire(self.tag, event, callback=onInviteJoin)

    def irc_unknown(self, prefix, command, params):
        log.debug(
            "Unknown RAW: %s; %s; %s",
            prefix, command, params
        )
        event = bones.event.IRCUnknownCommandEvent(self, prefix, command,
                                                   params)
        bones.event.fire(self.tag, event)

    def irc_ERR_NICKNAMEINUSE(self, prefix, params):
        event = bones.event.PreNicknameInUseError(self, prefix, params)

        def callback(event):
            if event.isCancelled is False:
                if len(self.factory.nicknames) > 0:
                    self.register(self.factory.nicknames.pop(0))
                    return
                irc.IRCClient.irc_ERR_NICKNAMEINUSE(
                    self, event.prefix, event.params
                )

        bones.event.fire(
            self.tag, event,
            callback=callback
        )

    def irc_JOIN(self, prefix, params):
        nick = prefix.split("!")[0]
        if nick.lower() == self.nickname.lower():
            self.joined(params[-1])
        else:
            self.userJoined(prefix, params[-1])

    def irc_PART(self, prefix, params):
        nick = prefix.split("!")[0]
        if nick.lower() == self.nickname.lower():
            self.left(params[0])
        else:
            msg = params[-1] if len(params) > 1 else None
            self.userLeft(prefix, params[0], msg)

    def irc_QUIT(self, prefix, params):
        self.userQuit(prefix, params[0])

    def left(self, channel):
        def callback(event):
            self.remove_channel(event.channel)

        event = bones.event.BotPartEvent(self, channel)
        bones.event.fire(self.tag, event, callback=callback)

    def ctcpQuery_VERSION(self, user, channel, data):
        if data is None and self.versionName:
            event = bones.event.CTCPVersionEvent(self, user)

            def eventCallback(thisEvent):
                if not event.isCancelled:
                    version = "%s %s %s" % (
                        self.versionName,
                        self.versionNum,
                        self.versionEnv,
                    )
                    version = version.replace("\n", "")
                    self.ctcpMakeReply(
                        event.user.nickname, [('VERSION', version)]
                    )
                    log.debug(
                        "Received CTCP VERSION query from %s, replied '%s'.",
                        user, version
                    )
                else:
                    log.debug(
                        "Received CTCP VERSION query from %s, but event was"
                        "cancelled by an eventhandler.",
                        user
                    )
            bones.event.fire(
                self.tag, event, callback=eventCallback
            )

    def sendLine(self, line):
        log.raw(line)
        irc.IRCClient.sendLine(self, line)

    def lineReceived(self, line):
        log.raw(line)
        irc.IRCClient.lineReceived(self, line)

    def quit(self, message=None):
        event = bones.event.BotPreQuitEvent(self, message)

        def doQuit(event):
            if event.quitMessage:
                self.sendLine("QUIT :{}".format(event.quitMessage))
            else:
                self.sendLine("QUIT")
        bones.event.fire(self.tag, event, callback=doQuit)


class BonesBotFactory(protocol.ClientFactory):
    """The Twisted client factory that provides connection management
    and configuration for each individual bot configuration.


    .. attribute:: sourceURL

        A hardcoded string URL to the Bones IRC Bot repository. Sent
        to clients in response to a :code:`CTCP SOURCEURL` query.

    .. attribute:: versionEnv

        Currently unused. Sent to clients as a part of a
        :code:`CTCP VERSION` reply.

    .. attribute:: versionName

        The name of the bot. Sent to clients as a part of a
        :code:`CTCP VERSION` reply.

    .. attribute:: versionNum

        The release name of the current bot version. Sent to clients
        as a part of a :code:`CTCP VERSION` reply.
    """

    sourceURL = "https://github.com/404d/Bones-IRCBot"
    versionName = "Bones IRCBot"
    versionNum = "0.2.0-DEV"
    versionEnv = ""

    protocol = BonesBot

    def __init__(self, settings):
        self.client = None
        self.modules = []
        self.tag = settings.server
        self.reconnect = True

        self.urlopener = urllib2.build_opener()
        self.urlopener.addheaders = [
            ('User-agent', 'urllib/2 BonesIRCBot/%s' % self.versionNum)
        ]

        self.reconnectAttempts = 0

        self.settings = settings
        self.channels = settings.get("server", "channel", default="") \
            .split("\n")
        self.channels = removeEmptyElementsFromList(self.channels)
        self.nicknames = settings.get("bot", "nickname", default="") \
            .split("\n")
        self.nicknames = removeEmptyElementsFromList(self.nicknames)
        try:
            self.nickname = self.nicknames.pop(0)
        except IndexError:
            raise InvalidConfigurationException(
                "No nicknames configured, property bot.nickname does not "
                "exist or is empty."
            )
        self.realname = settings.get("bot", "realname", default=self.nickname)
        self.username = settings.get("bot", "username")
        if not self.username:
            try:
                import getpass
                self.username = getpass.getuser()
            except:
                pass
        if not self.username:
            self.username = "bones"

        # Build the trigger regex using the trigger prefixes
        # specified in settings
        prefixChars = settings.get("bot", "triggerPrefixes", default="+") \
            .decode("utf-8")
        regex = "^([%s])([^ ]*)( .+)*?$" % prefixChars
        self.reCommand = re.compile(regex, re.UNICODE)

        modules = settings.get("bot", "modules", default="").split("\n")
        modules = removeEmptyElementsFromList(modules)
        for module in modules:
            self.loadModule(module)
        self.reconnect = True
        reactor.addSystemEventTrigger('before', 'shutdown',
                                      self.twisted_shutdown)
        bones.event.fire(self.tag, bones.event.BotInitializedEvent(self))

    def loadModule(self, path):
        """Loads the specified module and adds it to the bot if it is a
        valid :term:`Bones module`.

        :param path: The Python dot-notation path to the module that should be
            loaded.
        :type path: str.

        :raises:
            :class:`~bones.bot.BonesModuleAlreadyLoadedException,`
            :class:`~bones.bot.InvalidBonesModuleException,`
            :class:`~bones.bot.InvalidConfigurationException,`
            :class:`~bones.bot.NoSuchBonesException`
        """
        tmppath = path.split(".")
        package = ".".join(tmppath[:-1])
        name = tmppath[-1]

        log.info("Loading module %s", path)
        try:
            module = __import__(package, fromlist=[name])
        except ImportError as ex_raised:
            ex = NoSuchBonesModuleException(
                "Could not load module %s: No such package. "
                "(ImportException: %s)" %

                (path, ex_raised.message)
            )
            log.exception(ex)
            raise ex

        try:
            module = getattr(module, name)
        except AttributeError as ex_raised:
            ex = NoSuchBonesModuleException(
                "Could not load module %s: No such class. "
                "(AttributeException: %s)" %

                (path, ex_raised.message)
            )
            log.exception(ex)
            raise ex

        if issubclass(module, Module):
            if module in [m.__class__ for m in self.modules]:
                ex = BonesModuleAlreadyLoadedException(
                    "Could not load module %s: Module already loaded" %
                    (path,)
                )
                log.exception(ex)
                raise ex
            instance = module(settings=self.settings, factory=self)
            self.modules.append(instance)
            bones.event.register(instance, self.tag)
            bones.event.fire(self.tag, bones.event.BotModuleLoaded(module))
        else:
            ex = InvalidBonesModuleException(
                "Could not load module %s: Module is not a subclass of "
                "bones.bot.Module" %

                path
            )
            log.exception(ex)
            raise ex

    def buildProtocol(self, addr):
        if not self.reconnect:
            raise Exception
        self.client = protocol.ClientFactory.buildProtocol(self, addr)
        return self.client

    def clientConnectionLost(self, connector, reason):
        """Called when the connection to the server was lost. This method
        will take care of reconnecting the bot to the server after a variable
        time period.
        """
        event_args = (self, connector, reason)
        bones.event.fire(self.tag,
                         bones.event.ConnectionClosedEvent(*event_args))

        if not self.reconnect:
            reactor.callLater(0.0, self.shutdown_deferred.callback, 1)
            return
        self.client = None

        bones.event.fire(self.tag,
                         bones.event.ConnectionLostEvent(*event_args))

        time = 10.0 * self.reconnectAttempts
        self.reconnectAttempts += 1
        log.info(
            "{%s} Lost connection (%s), reconnecting in %i seconds.",
            self.tag, reason, time
        )
        reactor.callLater(time, connector.connect)

    def clientConnectionFailed(self, connector, reason):
        """Called when an error occured with the connection. This method
        will take care of reconnecting the bot to the server after a variable
        time period.
        """
        event_args = (self, connector, reason)
        bones.event.fire(self.tag,
                         bones.event.ConnectionClosedEvent(*event_args))

        if not self.reconnect:
            reactor.callLater(0.0, self.shutdown_deferred.callback, 1)
            return
        self.client = None

        bones.event.fire(self.tag,
                         bones.event.ConnectionFailedEvent(*event_args))

        time = 30.0 * self.reconnectAttempts
        self.reconnectAttempts += 1
        log.info(
            "{%s} Could not connect (%s), reconnecting in %i seconds.",
            self.tag, reason, time
        )
        reactor.callLater(time, connector.connect)

    def connect(self):
        """Connects this bot factory to the server it is configured for.
        Gets called automatically by the default manager at boot.
        """

        serverPort = int(self.settings.get("server", "port", default="6667"))
        serverHost = self.settings.get("server", "host")
        if not serverHost:
            raise InvalidConfigurationException(
                "Server {} does not contain a `host` option.".format(self.tag)
            )
        log_serverHost = serverHost
        if ":" in serverHost and not serverHost.startswith("[") \
                and not serverHost.endswith("]"):
            # IPv6 address, but not enclosed in brackets
            log_serverHost = "[%s]" % serverHost
        elif ":" in serverHost and (serverHost.startswith("[") and
                                    serverHost.endswith("]")):
            # IPv6 address and enclosed in brackets
            serverHost = serverHost[1:-1]
        if self.settings.get("bot", "bindAddress", default=None):
            bind_address = (self.settings.get("bot", "bindAddress"), 0)
            # Strip brackets if we're getting an IPv6 address
            if ":" in bind_address[0] and (bind_address[0].startswith("[") and
                                           bind_address[0].endswith("]")):
                bind_address = (bind_address[0][1:-1], bind_address[1])
        else:
            bind_address = None

        bones.event.fire(self.tag, bones.event.ConnectionStartedEvent(
            self, serverHost, serverPort, bind_address
        ))

        if self.settings.get("server", "useSSL", default="false") == "true":
            log.info("Connecting to server %s:+%i", log_serverHost, serverPort)
            try:
                from twisted.internet import ssl
            except ImportError:
                ex = Exception(
                    "Unmet dependency: pyOpenSSL not installed. This "
                    "dependency needs to be installed before you can use SSL "
                    "server connections"
                )
                log.exception(ex)
                raise ex
            reactor.connectSSL(
                serverHost, serverPort, self, ssl.ClientContextFactory(),
                bindAddress=bind_address
            )
        else:
            log.info("Connecting to server %s:%i", log_serverHost, serverPort)
            reactor.connectTCP(serverHost, serverPort, self,
                               bindAddress=bind_address)

    def twisted_shutdown(self):
        self.shutdown_deferred = defer.Deferred()
        self.reconnect = False

        def shutdown_hook(self):
            if self.client:
                self.client.quit(self.settings.get("bot", "quitMessage",
                                                   default="Reactor shutdown"))
            else:
                reactor.callLater(0.0, self.shutdown_deferred.callback, 1)
        reactor.callLater(0.0, shutdown_hook, self)
        return self.shutdown_deferred


class Module():
    """:term:`Bones module` base class

    :param settings: The settings for the current server factory.
    :type settings: :class:`bones.config.ServerConfiguration`
    :param factory: The bot factory that instanciated this module.
    :type factory: :class:`bones.bot.BonesBotFactory`

    .. attribute:: settings

        A :class:`bones.config.ServerConfiguration` instance containing all the
        currently loaded settings for this server factory and all its bots and
        modules.

    .. attribute:: factory

        A :class:`bones.bot.BonesBotFactory` instance representing the factory
        which instanciates the clients whom this module is used with.
    """

    def __init__(self, settings, factory):
        self.settings = settings
        self.factory = factory
        self.name = "%s.%s" % (self.__module__, self.__class__.__name__)
        self.log = logging.getLogger(self.name)
