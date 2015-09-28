import inspect
import logging

from twisted.internet import threads

log = logging.getLogger(__name__)

eventHandlers = {}


def is_handler(x):
    return inspect.ismethod(x) or inspect.isfunction(x)


def fire(server, event, *args, **kwargs):
    """Call all event handlers with the specified event identifier
    registered to the provided server with the provided arguments.

    This may be called in your :term:`Bones module` to fire custom events.

    .. note::

        You should create a class that inherits from
        :class:`~bones.event.Event`, and put your arguments inside this.

    .. warning::

        Using this to alter standard bot behaviour is not supported! This means
        doing anything like (but not limited to) firing events that are
        supposed to be handled by the bot core, for example
        :class:`~bones.event.PrivmsgEvent`.

    :param server: the server tag that identifies the server this occured on
    :type server: str
    :param event: an event instance or event identifier
    :type event: object
    :param callback: a callable that should be called after all event handlers
        have been triggered
    :type callback: callable
    """
    def threadedFire(server, event, *args, **kwargs):
        callback = None
        if "callback" in kwargs:
            callback = kwargs["callback"]
            del kwargs["callback"]
        if isinstance(event, Event):
            args = (event,) + args
            event = event.__class__
        if server.lower() in eventHandlers:
            if event in eventHandlers[server.lower()]:
                for h in eventHandlers[server.lower()][event]:
                    try:
                        h['f'](h['c'], *args, **kwargs)
                    except Exception as ex:
                        log.exception(ex)
        if callback:
            callback(*args, **kwargs)
    threads.deferToThread(threadedFire, server, event, *args, **kwargs)


def handler(event=None, trigger=None):
    """Marks the decorated callable as an event handler for the given type of
    :term:`event`, or as a trigger handler for the given :term:`trigger`.

    .. note:: For all events that are tied to Bones core, the event identifier
        is the class definition of an event.

    .. warning:: You are free to use one callable for multiple events or
        multiple triggers, but it is not supported to use the same callable for
        both event handling and trigger handling.

    :param event: the identifier for the event you are going to handle
    :type event: object
    :param trigger: the trigger command to react to
    :type trigger: str
    """
    def realHandler(func):
        if event is not None or trigger is not None:
            if getattr(func, '_event', None) is None:
                func._event = []
            if event and not trigger:
                func._event.append(event)
            if trigger and not event:
                func._event.append("<Trigger: %s>" % trigger.lower())
            if trigger and event:
                log.error(
                    "Can't register both an event and a trigger with the same "
                    "bones.event.handler call."
                )
        return func
    return realHandler


def register(obj, server):
    """Look through a Module for registered event handlers and add
    them to the event handler list.

    This is an internal function automatically called by the server bot
    factory while creating the factory. **Do not** call this in your
    modules!

    :param obj: the :class:`Module` instance to look at.
    :type obj: :class:`bones.bot.Module`
    :param server: the server tag that the supplied module runs under.
    :type server: :class:`bones.bot.BonesBot`
    """
    klass = obj.__class__
    for name, method in inspect.getmembers(klass, is_handler):
        if getattr(method, '_event', None) is not None:
            for event in method._event:
                if server.lower() not in eventHandlers:
                    eventHandlers[server.lower()] = {}
                if event not in eventHandlers[server.lower()]:
                    eventHandlers[server.lower()][event] = []
                eventHandlers[server.lower()][event].append({
                    "c": obj,
                    "f": method,
                })


class Target():
    """Utility class providing easy access to methods commonly used against
    targets.

    :param name: a string identifying the message target, as used in protocol
        message :code:`MSG targetNameHere :Message to be sent`
    :type name: string
    :param server: the :class:`~bones.bot.BonesBot` client instance that will
        be used to send messages to this target.
    :type server: :class:`bones.bot.BonesBot`

    .. attribute:: name

        String with the target name. This could for example be a nick, a
        hostname or a channel name.

    .. attribute:: server

        :class:`~bones.bot.BonesBot` instance that will be used to send the
        messages to the target.
    """
    def __init__(self, name, server):
        self.name = name
        self.server = server

    def msg(self, msg):
        """Sends the provided message to the represented target.

        :param msg: message to be sent.
        :type msg: string
        """
        self.server.msg(self.name, msg)

    def notice(self, msg):
        """Sends the provided message as a notice to the represented target.

        :param msg: message to be sent as a notice
        :type msg: string
        """
        self.server.notice(self.name, msg)


class User(Target):
    """Utility class turning a hostmask into distinguishable nickname,
    user and hostname attributes.

    :param mask: The IRC hostmask to be parsed. Ex:
        :code:`Bones!bot@192.168.0.2`
    :type mask: str
    :param server: :class:`~bones.bot.BonesBot` instance representing
        the server connection where we can reach this user.
    :type server: :class:`bones.bot.BonesBot`

    .. attribute:: mask

        A string of the hostmask that this object originated from.

    .. attribute:: nickname

        A string of the nickname for the provided hostmask. Given
        the hostmask above, the nickname will be :code:`Bones`.

    .. attribute:: hostname

        A string of the hostname for the provided hostmask. Given
        the hostmask above, the hostname will be :code:`192.168.0.2`.
        If the provided hostmask is missing the hostname part, this will
        be :code:`None`.

    .. attribute:: username

        A string of the username for the provided hostmask. Given
        the hostmask above, the username will be :code:`bot`.
        If the provided hostmask is missing the username part, this will
        be :code:`None`.
    """
    def __init__(self, mask, server):
        self.mask = mask
        tmp = mask.split("!")
        Target.__init__(self, tmp[0], server)
        if len(tmp) > 1:
            tmp = tmp[1].split("@")
            self.username = tmp[0]
            self.hostname = tmp[1]
        else:
            self.username = None
            self.hostname = None
        self.channels = []
        self.user_modes = {}

    def __repr__(self):
        return "<User %s!%s@%s{%s}>" % (
            self.nickname,
            self.username if self.username else "",
            self.hostname if self.hostname else "",
            self.server.tag
        )

    def _get_nickname(self):
        return self.name
    nickname = property(_get_nickname)

    def kick(self, channel, reason=None):
        """
        Kicks the user from the specified channel.

        .. attribute:: reason

            A string that will be supplied with the kick as a reason for the
            kick.

        .. attribute:: channel

            The :class:`~bones.event.Channel` instance that represents the
            channel the user is to be kicked from.
        """
        self.server.kick(channel.name, self.name, reason)

    def ping(self):
        """Sends the user a CTCP PING query."""
        self.server.ping(self.name)


class Channel(Target):
    """Utility class representing a channel on a server.

    .. attribute:: modes

        A dictionary of mode-value pairs representing the modes in
        the channel. Modes such as :code:`+b` will be added to and
        removed from this list when the bot sees them.

    .. attribute:: users

        A list of user instances representing all the users in the
        channel.

    .. attribute:: topic

        An :class:`~bones.event.Topic` instance containing the current
        topic and the user that wrote it.
    """
    def __init__(self, name, server):
        Target.__init__(self, name, server)
        self.modes = {}
        self.users = []
        self.topic = None

    def __repr__(self):
        return "<Channel %s{%s}>" % (self.name, self.server.factory.tag)

    def _cleanup(self):
        for user in self.users:
            if self in user.channels:
                user.channels.remove(self)
        del self.users
        self.server = None

    def _remove_user(self, user):
        if user in self.users:
            self.users.remove(user)
        if self in user.channels:
            user.channels.remove(self)
        for m, p in self.server.prefixes:
            if m in self.modes and user.nickname in self.modes[m]:
                self.modes[m].remove(user.nickname)

    def _set_modes(self, modes, args, set):
        for mode in modes:
            if set:
                self._set_mode(mode, args)
            else:
                self._unset_mode(mode, args)

    def _set_mode(self, mode, args):
        if mode in self.server.channel_modes["list"] or \
                [True for m, p in self.server.prefixes if m == mode]:
            if mode not in self.modes:
                log.debug("Creating modelist '%s' for %s", mode, self)
                self.modes[mode] = set()
            log.debug("Adding element '%s' to modelist '%s' in %s", args[0],
                      mode, self)
            self.modes[mode].add(args.pop(0))
        elif mode in self.server.channel_modes["always"]:
            log.debug("Setting value-mode '%s' with argument '%s' in %s", mode,
                      args[0], self)
            self.modes[mode] = args.pop(0)
        elif mode in self.server.channel_modes["set"]:
            log.debug("Setting option-mode '%s' with argument '%s' in %s",
                      mode, args[0], self)
            self.modes[mode] = args.pop(0)
        else:
            log.debug("Setting boolean mode '%s' in %s", mode, self)
            self.modes[mode] = True

    def _unset_mode(self, mode, args):
        if mode in self.server.channel_modes["list"] or \
                [True for m, p in self.server.prefixes if m == mode]:
            arg = args.pop(0)
            if mode in self.modes and arg in self.modes[mode]:
                log.debug("Removing element '%s' from modelist '%s' in %s",
                          arg, mode, self)
                self.modes[mode].remove(arg)
            else:
                log.debug("Ignoring modelist '%s' removal of '%s' in %s",
                          mode, arg, self)
        elif mode in self.server.channel_modes["always"]:
            arg = args.pop(0)
            if mode in self.modes and arg:
                log.debug("Removing value-mode '%s' ('%s') from channel %s",
                          mode, arg, self)
                del self.modes[mode]
            else:
                log.debug("Ignoring value-mode removal of '%s' ('%s') in %s",
                          mode, arg, self)
        elif mode in self.server.channel_modes["set"]:
            if mode in self.modes:
                log.debug("Removing option-mode '%s' from %s", mode, self)
                del self.modes[mode]
            else:
                log.debug("Ignoring option-mode removal of '%s' from %s", mode,
                          self)
        else:
            if mode in self.modes:
                log.debug("Removing boolean mode '%s' from %s", mode, self)
                del self.modes[mode]
            else:
                log.debug("Ignoring boolean mode removal of '%s' from %s",
                          mode, self)

    def kick(self, user, reason=None):
        """
        Kick a user from the channel.

        :param user: The user that should be kicked.
        :type user: :class:`~bones.event.User`

        :param reason: A message that will be shown to users in the channel
            when kicking :code:`user`.
        :type reason: str
        """
        self.server.kick(self.name, user.name, reason)

    def part(self, reason=None):
        """
        Makes the bot part the channel.

        :param reason: The part message that will be sent to the channel when
            parting the channel.
        :type reason: str
        """
        self.server.part(self.name, reason)

    def setTopic(self, topic):
        """
        Changes the channel's topic.

        :param topic: The topic that should be changed to.
        :type topic: str
        """
        self.server.topic(self.name, topic)


class Topic():
    """Utility class representing a topic in a channel.

    .. attribute:: text
        :type: str

        The channel's current topic.

    .. attribute:: user

        An instance of :class:`~bones.event.User` that represents
        the user that wrote the topic.
    """
    def __init__(self, topic, user):
        self.text = topic
        self.user = user


# ------------------------------------ #


class Event():
    pass


class BotModuleLoaded(Event):
    """
    Called by the :class:`~bones.bot.BonesBotFactory` when a module is
    loaded during initialization.

    .. attribute:: module

        The module instance that were initialized and loaded.
    """
    def __init__(self, module):
        self.module = module


class BotNoticeReceivedEvent(Event):
    """
    Fired whenever the bot receives a notice.

    .. attribute:: client

        The client instance that this event applies to.

    .. attribute:: user

        A string representing the nickname of the user that sent the notice.

    .. attribute:: channel

        A string representing the name of the channel that the notice were sent
        to.

    .. attribute:: message

        The message that was sendt as part of the notice.
    """
    def __init__(self, client, user, channel, message):
        self.client = client
        self.user = user
        self.channel = channel
        self.message = message


class BotInitializedEvent(Event):
    """
    An event that is fired whenever the bot factory for a configuartion
    has been initialized and is ready to connect to the server.

    .. attribute:: factory

        The :class:`~bones.bot.BonesBotFactory` instance which was initialized.
    """
    def __init__(self, factory):
        self.factory = factory


class BotInviteEvent(Event):
    """
    An event that is fired whenever the bot joins a new channel. The bot has
    "joined" a channel when the server informs the bot of its presence in that
    channel, and not when the bot calls
    :class:`client.join("#channel")`.

    .. attribute:: client

        The client instance that this event applies to.

    .. attribute:: channel

        The channel name the bot was invited to, as a string.

    .. attribute:: inviter

        The user that invited the bot, as a :class:`~bones.event.User`
        instance..
    """
    def __init__(self, client, channel, inviter):
        self.client = client
        self.channel = channel
        self.inviter = inviter
        self.isCancelled = False


class BotJoinEvent(Event):
    """
    An event that is fired whenever the bot joins a new channel. The bot has
    "joined" a channel when  the server informs the bot of its presence in that
    channel, and not when the bot calls
    :class:`client.join("#channel")`.

    .. attribute:: client

        The client instance that this event applies to.

    .. attribute:: channel

        A :class:`~bones.event.Channel` instance representing the channel that
        were joined by the bot.
    """
    def __init__(self, client, channel):
        self.client = client
        self.channel = channel


class BotKickedEvent(Event):
    """
    An event that is fired whenever the bot gets kicked from a channel it is
    in.

    .. attribute:: client

        The client instance that this event applies to.

    .. attribute:: channel

        A :class:`~bones.event.Channel` instance representing the channel that
        the bot was kicked form.

    .. attribute:: kicker

        A :class:`~bones.event.User` instance representing the user that kicked
        the bot.

    .. attribute:: message

        The kick reason as specified by the kicker, as a string.
    """
    def __init__(self, client, channel, kicker, message):
        self.client = client
        self.channel = channel
        self.kicker = kicker
        self.message = message


class BotNickChangedEvent(Event):
    """
    Called by the bot when its nickname has changed, either by the bot
    itself or something like services, nick collision or the like.

    .. attribute:: client

        The client instance that this event applies to.

    .. attribute:: nick

        The new nickname that the bot now goes by.
    """
    def __init__(self, client, nick):
        self.client = client
        self.nick = nick


class BotPartEvent(Event):
    """An event that is fired whenever the bot leaves a channel.

    :param client: The bot instance that this event originated from.
    :type client: :class:`bones.bot.BonesBot`
    :param channel: The name of the channel the bot parted from.
    :type channel: str.

    .. attribute:: channel

        A string representation of the name of the channel the bot parted from.

    .. attribute:: client

        The :class:`bones.bot.BonesBot` instance representing the connection
        to the server that this event originated from.
    """
    def __init__(self, client, channel):
        self.client = client
        self.channel = channel


class BotPreJoinEvent(Event):
    """
    Called by the bot before the bot joins a channel. This may be
    used to prevent the bot from joining a channel.

    .. attribute:: client

        The client instance that this event applies to.

    .. attribute:: channel

        The channel that the bot is trying to join, in string format.

    .. attribute:: isCancelled

        A boolean that tells the bot whether to stop this event
        chain and prevent the bot from joining a channel.

    """
    def __init__(self, client, channel):
        self.isCancelled = False
        self.client = client
        self.channel = channel


class BotPreQuitEvent(Event):
    def __init__(self, client, quitMessage):
        self.client = client
        self.quitMessage = quitMessage


class ConnectionClosedEvent(Event):
    """
    Called by a bot factory whenever its connection gets closed.

    .. attribute:: factory

        The bot factory whose connection was closed.

    .. attribute:: connector

        The :class:`twisted.internet.tcp.Connector` instance that represents
        the closed connection.

    .. attribute:: reason

        A Twisted error instance representing the reason that the connection
        was closed.

    """
    def __init__(self, factory, connector, reason):
        self.factory = factory
        self.connector = connector
        self.reason = reason


class ConnectionFailedEvent(ConnectionClosedEvent):
    """
    Called by a bot factory whenever its connection fails.

    .. attribute:: factory

        The bot factory whose connection failed.

    .. attribute:: connector

        The :class:`twisted.internet.tcp.Connector` instance that represents
        the failed connection.

    .. attribute:: reason

        A Twisted error instance representing the reason that the connection
        failed.

    """
    pass


class ConnectionLostEvent(ConnectionClosedEvent):
    """
    Called by a bot factory whenever its connection was lost.

    .. attribute:: factory

        The bot factory whose connection was lost.

    .. attribute:: connector

        The :class:`twisted.internet.tcp.Connector` instance that represents
        the lost connection.

    .. attribute:: reason

        A Twisted error instance representing the reason that the connection
        was lost.

    """
    pass


class ConnectionStartedEvent(Event):
    """
    Called by a bot factory when it's done preparing a server connection.

    .. attribute:: factory

        The bot factory whose connection has been prepared.

    .. attribute:: host

        A string representation of the host address the bot will connect to.

    .. attribute:: port

        The port of the target host that we're connecting to.

    .. attribute:: bind_address

        An address-port tuple (string, int) representing the local address the
        bot will bind to.

    """
    def __init__(self, factory, host, port, bind_address):
        self.factory = factory
        self.host = host
        self.port = port
        self.bind_address = bind_address


class PreNicknameInUseError(Event):
    """
    An event that is fired before the bot's username is changed because
    of collision. As the bot's default behaviour tells it to cycle through
    all of the nicks in the bot nickname list, this may be used to prevent
    floods when changing the nickname by hand. An example use of this event
    is available in the :class:`bones.modules.utilities.NickFix` module that
    makes the bot try to recover its nick if it is in use.

    .. attribute:: client

        The client instance that this event applies to.

    .. attribute:: isCancelled

        A boolean that tells the bot whether to stop this event
        chain and prevent the bot from automatically changing its
        nick.
    """
    def __init__(self, client, prefix, params):
        self.isCancelled = False
        self.client = client
        self.prefix = prefix
        self.params = params


class BotSignedOnEvent(Event):
    """An event which is fired whenever the bot finishes connecting
    and registrating with the server.

    :param client: The bot instance that this event originates from.
    :type client: :class:`bones.bot.BonesBot`

    .. attribute:: client

        The client instance that this event applies to.
    """
    def __init__(self, client):
        self.client = client


class BounceEvent(Event):
    def __init__(self, client, info):
        self.client = client
        self.info = info


class ChannelTopicChangedEvent(Event):
    def __init__(self, client, user, channel, newTopic):
        self.client = client
        self.user = user
        self.channel = channel
        self.newTopic = newTopic


class CTCPVersionEvent(Event):
    """
    Fired by the bot after a CTCP VERSION has been received. This
    event may be used to cancel the CTCP VERSION reply that is
    usually sent.

    .. attribute:: client

        The client instance that this event applies to.

    .. attribute:: isCancelled

        A boolean that tells the bot whether to stop this event
        chain and prevent the bot from joining a channel.

    .. attribute:: user

        The user that sent the CTCP VERSION request, as a
        :class:`bones.event.User` instance.
    """
    def __init__(self, client, user):
        self.isCancelled = False
        self.client = client
        self.user = User(user, client)


class CTCPPongEvent(Event):
    """
    Fired by the bot after a CTCP PING reply has been received. This
    event may be used to get the result of a :code:`client.ping`
    request.

    .. attribute:: client

        The client instance that this event applies to.

    .. attribute:: secs

        Time elapsed since the ping request started, in seconds as a float.

    .. attribute:: user

        The user that sent the CTCP VERSION request, as a
        :class:`bones.event.User` instance.
    """
    def __init__(self, client, user, secs):
        self.client = client
        self.secs = secs
        self.user = User(user, client)


class IrcPrivmsgEvent(Event):
    """Event fired when the bot receives a message from another user,
    either over a query or from a channel.

    :param client: A :class:`~bones.bot.BonesBot` instance representing the
        current server connection.
    :type client: :class:`bones.bot.BonesBot`
    :param user: The hostmask of the user who sent this message.
    :type user: :class:`bones.event.User`
    :param channel: A :class:`~bones.event.Target` instance representing the
        communication target this message was sent to.
    :type channel: :class:`bones.event.Target`
    :param message: The message that was sent to the target.
    :type message: string

    .. attribute:: client

        A :class:`~bones.bot.BonesBot` instance representing the server
        connection which received this event.

    .. attribute:: message

        The message string that was sent.

    .. attribute:: channel

        A :class:`~bones.bot.Target` instance representing the communication
        channel this message was sent to. This may be an object something that
        inherits `~bones.bot.Target`, like `~bones.bot.Channel` and
        `~bones.bot.User`.

    .. attribute:: user

        A :class:`~bones.bot.User` instance representing the user that sent the
        message.
    """
    def __init__(self, client, user, channel, message):
        self.client = client
        self.user = user
        self.channel = channel
        self.message = message

    def reply(self, message, separator=": "):
        """Sends `message` to `self.channel`. Prepends the nickname of the target user
        plus `separator` if `self.channel` is a user instance.

        :param message: The reply to this event.
        :type message: string
        :param separator: The separator used between a `~bones.event.User`'s
            nickname and the provided message.
        :type message: string
        :default message: ": "
        """
        if not isinstance(self.channel, User):
            message = "".join([self.user.nickname, separator, message])
        self.channel.msg(message)


class ChannelMessageEvent(IrcPrivmsgEvent):
    pass


class IRCUnknownCommandEvent(Event):
    """
    Fired whenever the bot encouters an unknown numeric reply and/or command.

    .. attribute:: client

        The client instance that this event applies to.

    .. attribute:: prefix

        The sender of the unknown command.

    .. attribute:: command

        The numeric or string representation of the unknown command.

    .. attribute:: params

        All supplied parameters, as a list.
    """
    def __init__(self, client, prefix, command, params):
        self.client = client
        self.prefix = prefix
        self.command = command
        self.params = params


class ModeChangedEvent(Event):
    def __init__(self, client, user, channel, set, modes, args):
        self.client = client
        self.user = user
        self.channel = channel
        self.set = set
        self.modes = modes
        self.args = args


class PrivmsgEvent(Event):
    """Event fired when the bot receives a message from another user,
    either over a query or from a channel.

    .. deprecated:: Use `bones.event.IrcPrivmsgEvent` instead.

    :param client: A :class:`~bones.bot.BonesBot` instance representing the
        current server connection.
    :type client: :class:`bones.bot.BonesBot`
    :param user: The hostmask of the user who sent this message.
    :type user: string
    :param channel: A :class:`~bones.event.Target` instance representing the
        communication target this message was sent to.
    :type channel: :class:`bones.event.Target`
    :param msg: The message that was sent to the target.
    :type msg: string

    .. attribute:: client

        A :class:`~bones.bot.BonesBot` instance representing the server
        connection which received this event.

    .. attribute:: msg

        The message string that was sent.

    .. attribute:: channel

        A :class:`~bones.bot.Target` instance representing the communication
        channel this message was sent to. This may be an object something that
        inherits `~bones.bot.Target`, like `~bones.bot.Channel` and
        `~bones.bot.User`.

    .. attribute:: user

        A :class:`~bones.bot.User` instance representing the user that sent the
        message.
    """
    def __init__(self, client, user, channel, msg):
        self.client = client
        self.channel = channel
        self.user = User(user, client)
        self.msg = msg


class ServerChannelCountEvent(Event):
    """
    Fired when the bot receives the :code:`RPL_LUSERCHANNELS` numeric.

    .. attribute:: client

        A :class:`~bones.bot.BonesBot` instance that represents the client
        that received this numeric reply.

    .. attribute:: channels

        The server channel count, as an integer.
    """
    def __init__(self, client, channels):
        self.client = client
        self.channels = channels


class ServerCreatedEvent(Event):
    """
    Fired when the bot receives the :code:`RPL_CREATED` numeric.

    .. attribute:: client

        A :class:`~bones.bot.BonesBot` instance that represents the client
        that received this numeric reply.

    .. attribute:: when

        The creation date, as a string.
    """
    def __init__(self, client, when):
        self.client = client
        self.when = when


class ServerClientInfoEvent(Event):
    """
    Fired when the bot receives the :code:`RPL_LUSERCLIENT` numeric.

    .. attribute:: client

        A :class:`~bones.bot.BonesBot` instance that represents the client
        that received this numeric reply.

    .. attribute:: info

        The client info, as a string.
    """
    def __init__(self, client, info):
        self.client = client
        self.info = info


class ServerHostInfoEvent(Event):
    """
    Fired when the bot receives the :code:`RPL_YOURHOST` numeric.

    .. attribute:: client

        A :class:`~bones.bot.BonesBot` instance that represents the client
        that received this numeric reply.

    .. attribute:: info

        The server info, as a string.
    """
    def __init__(self, client, info):
        self.client = client
        self.info = info


class ServerInfoEvent(Event):
    """
    Fired when the bot receives the :code:`RPL_MYINFO` numeric.

    .. attribute:: client

        A :class:`~bones.bot.BonesBot` instance that represents the client
        that received this numeric reply.

    .. attribute:: servername

        The name of the current server, as a string.

    .. attribute:: version

        The version info of the current server, as a string.

    .. attribute:: umodes

        The supported user modes on the current server.

    .. attribute:: cmodes

        The supported channel modes on the current server.
    """
    def __init__(self, client, servername, version, umodes, cmodes):
        self.client = client
        self.servername = servername
        self.version = version
        self.umodes = umodes
        self.cmodes = cmodes


class ServerLocalInfoEvent(Event):
    """
    Fired when the bot receives the :code:`RPL_LUSERME` numeric.

    .. attribute:: client

        A :class:`~bones.bot.BonesBot` instance that represents the client
        that received this numeric reply.

    .. attribute:: info

        The server info, as a string.
    """
    def __init__(self, client, info):
        self.client = client
        self.info = info


class ServerMOTDReceivedEvent(Event):
    def __init__(self, client, motd):
        self.client = client
        self.motd = motd


class ServerOpCountEvent(Event):
    """An event that is fired during server connection. This event details
    how many operators are connected to the server.

    :param client: The bot instance for the server this event originated from.
    :type client: :class:`bones.bot.BonesBot`

    .. attribute:: client

        A :class:`bones.bot.BonesBot` instance representing the server
        connection which received this event.

    .. attribute:: ops

        The number of local operators connected to the server, as an integer.
    """
    def __init__(self, client, ops):
        self.client = client
        self.ops = ops


class ServerSupportEvent(Event):
    """An event that is fired whenever the bot receives an :code:`ISUPPORT`
    during connection. This should be used by your :term:`Bones module` if
    you for example need :code:`WATCH` for your module to work.

    :param client: The bot instance for the server this event originated from.
    :type client: :class:`bones.bot.BonesBot`

    .. attribute:: client

        A :class:`bones.bot.BonesBot` instance representing the server
        connection which received this event.

    .. attribute:: options

        A list of all the different options the server supports, in strings
        with the format "KEY=VALUE".
    """
    def __init__(self, client, options):
        self.client = client
        self.options = options


class TriggerEvent(ChannelMessageEvent):
    """An event that is fired by the bot whenever it receives a :code:`PRIVMSG`
    event that starts with a valid trigger prefix and is a valid command.

    :param client: The bot instance which the event originated from.
    :type client: :class:`bones.bot.BonesBot`
    :param args: A list of all the arguments provided with the trigger command.
    :type args: list
    :param user: The user which initiated this event.
    :type user: :class:`bones.bot.User`
    :param msg: The original message that was parsed to reveal the trigger
        command.
    :type msg: str.
    :param match: The Regular Expression match object containing additional
        information about the parsing of the trigger command.
    :type match: :class:`SRE_Match`


    .. seealso::

        :class:`Event`,
        :class:`ChannelMessageEvent`

    .. attribute:: args

        A list of strings containing all the arguments passed to the trigger
        command.

    .. attribute:: match

        The regex match object that was returned while parsing the original
        message, :attr:`msg`
    """
    def __init__(self, client, args=None, channel=None, user=None, msg=None,
                 match=None):
        ChannelMessageEvent.__init__(self, client, user, channel, msg)
        self.args = args
        self.match = match


class UserActionEvent(Event):
    """An event that is fired whenever another user sends a
    :code:`CTCP ACTION` to the channel.

    :param client: The bot instance where this event occured.
    :type client: :class:`bones.bot.BonesBot`
    :param user: The user that initiated this event.
    :type user: :class:`bones.event.User`
    :param channel: The channel the :code:`CTCP ACTION` was sent to.
    :type channel: str.
    :param data: The text which is actioned.
    :type data: str.

    .. attribute:: channel

        A string representation of the channel the :class:`User` joined.

    .. attribute:: client

        The :class:`bones.bot.BonesBot` instance representing the connection
        to the server that this event originated from.

    .. attribute:: data

        A string representing the text which was actioned. Using the following
        example,
        ::

            * Nickname slaps Operator around a bit with a large trout

        the actioned text is everything following the nickname and the space
        immediately following i, or in other words
        :code:`slaps Operator around a bit with a large trout`.

    .. attribute:: user

        A :class:`User` instance representing the user who initiated
        this event.
    """
    def __init__(self, client, user, channel, data):
        self.client = client
        self.user = user
        self.channel = channel
        self.data = data


class UserJoinEvent(Event):
    """An event that is fired whenever another user joins one
    of the channels the bot is in.

    :param client: The bot instance where this event occured.
    :type client: :class:`bones.bot.BonesBot`
    :param channel: The channel where this event occured.
    :type channel: str.
    :param user: The user who fired this event.
    :type user: :class:`User`

    .. attribute:: channel

        A string representation of the channel the :class:`User`
        joined.

    .. attribute:: client

        The :class:`bones.bot.BonesBot` instance representing the connection
        to the server that this event originated from.

    .. attribute:: user

        A :class:`User` instance representing the user who joined.
    """
    def __init__(self, client, channel, user):
        self.client = client
        self.channel = channel
        self.user = user


class UserMessageEvent(IrcPrivmsgEvent):
    pass


class UserNickChangedEvent(Event):
    """An event which is fired whenever a user in one of the joined channels
    changes his/her nickname.

    :param client: The bot instance that this event originated from.
    :param user: The user who changed his/her nickname.
    type user: :class:`bones.event.user`
    :param oldname: The previous nickname the user went by.
    :type oldname: str
    :param newname: The new nickname the user is now using.
    :type newname: str

    .. attribute:: client

        The :class:`bones.bot.BonesBot` instance representing the connection
        to the server that this event originated from.

    .. attribute:: user

        A :class:`~bones.event.User` instance representing the user who changed
        his/her nickname.

    .. attribute:: newname

        A string representation of the new nickname the user is using on the
        server.

    .. attribute:: oldname

        A string representation of the nickname the user went by on the server
        before the nickname change.

    """
    def __init__(self, client, user, oldname, newname):
        self.client = client
        self.user = user
        self.oldname = oldname
        self.newname = newname


class UserPartEvent(Event):
    """An event that is fired whenever a user leaves a channel. This should
    not be confused with a :class:`bones.event.UserQuitEvent`, which is sent
    only when a user quits from the server.

    A :class:`UserPartEvent` is sent once to each channel the user parts
    from. The user may still be connected to IRC, but the user is not
    available in the channel designated by the :attr:`channel` attribute.

    :param client: The bot instance that this event originated from.
    :type client: :class:`bones.bot.BonesBot`
    :param user: The the user who parted from the channel.
    :type user: :class:`bones.event.User`
    :param channel: The name of the channel the user parted from.
    :type channel: str.

    .. attribute:: channel

        A string representation of the name of the channel the user parted
        from.

    .. attribute:: client

        The :class:`bones.bot.BonesBot` instance representing the connection
        to the server that this event originated from.

    .. attribute:: user

        A :class:`~bones.event.User` instance representing the nickname of the
        user who parted from the channel.
    """
    def __init__(self, client, user, channel):
        self.client = client
        self.user = user
        self.channel = channel


class UserQuitEvent(Event):
    """An event that is fired whenever a user quits IRC, or in other words
    leaves the server. This may be either because of a ping timeout,
    server/IRC operator :code:`KILL` or the user sending :code:`QUIT` to the
    server. This event should not be confused with a
    :class:`bones.event.UserPartEvent`, which is sent once only when a user
    leaves a channel the bot is a part of.

    A :class:`UserQuitEvent` is sent once to the bot when the user quits from
    IRC, and does not mention what channels the user left while doing so. As
    such, when a :class:`UserQuitEvent` is sent all plugins should usually
    treat this as the user parted from all channels the users where in.

    The bot will not receive a :class:`UserQuitEvent` if the user has only been
    involved with the bot through a query, and not been in any of the channels
    the bot is in. The bot will also not receive a :class:`UserQuitEvent` if
    the user left all the channels the bot was in, and then :code:`QUIT` from
    IRC afterwards.

    :param client: The bot instance where this event occured.
    :type client: :class:`bones.bot.BonesBot`
    :param user: The user who quit IRC.
    :type user: :class:`bones.event.User`
    :param quitMessage: The message sent with the quit command.
    :type quitMessage: str.

    .. attribute:: client

        The :class:`bones.bot.BonesBot` instance representing the connection to
        the server where this event occured.

    .. attribute:: user

        A :class:`~bones.event.User` instance representing the nickname of the
        user who quit IRC.

    .. attribute:: quitMessage

        A string representing the message that was sent with the quit. This
        message is usually formated by the server so that user-specified
        quit messages doesn't look like i.e. a ping timeout or an operator
        :code:`KILL`.
    """
    def __init__(self, client, user, quitMessage):
        self.client = client
        self.user = user
        self.quitMessage = quitMessage


class UserKickedEvent(Event):
    """An event that is fired whenever a user have been kicked from a channel.

    :param client: The bot instance where this event occured.
    :type client: :class:`bones.bot.BonesBot`
    :param channel: The channel instance where this event occured.
    :type channel: :class:`bones.event.Channel`
    :param kickee: The nickname of the user who was kicked.
    :type kickee: :class:`User`
    :param kicker: The nickname of the user who kicked the kickee.
    :type kicker: :class:`User`
    :param message: The message provided with the kick, usually as a reason
        for the kick.
    :type message: str.

    .. attribute:: channel

        A :class:`bones.event.Channel` instance representing the channel
        where the kick occurred.

    .. attribute:: client

        A :class:`bones.bot.BonesBot` instance representing the server from
        which the event originated.

    .. attribute:: kickee

        A :class:`User` instance representing the nickname of the user who
        was kicked by the kicker.

    .. attribute:: kicker

        A :class:`User` instance representing the nickname of the user who
        kicked the kickee. This is the user who initiated this event.

    .. attribute:: message

        A string representing the message the kicker sent with the kick. This
        is often used as a reason for explaining the kick.
    """
    def __init__(self, client, kickee, channel, kicker, message):
        self.client = client
        self.channel = channel
        self.kickee = kickee
        self.kicker = kicker
        self.message = message
