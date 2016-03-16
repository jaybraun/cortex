#!/usr/bin/env python

import os
import argparse
import ConfigParser
import logging
import json
import subprocess

from uuid import uuid4 as UUID

from stompest.config import StompConfig
from stompest.sync import Stomp
from stompest.protocol import StompSpec

# Section of the config file for base class properties
BASE_SECTION = "main"

class Worker(object):
    """Worker

    Worker agent that subscribes to messages from an Apollo server, does some
    kind of work, and possibly publishes a result back to Apollo.
    """
    def __init__(self, subclass_section=None):
        self.args = self.__parse_all_params(subclass_section)
        self.apollo_conn = None
        #TODO: make this a class?
        self.transactions = {}

    def __parse_all_params(self, subclass_section=None):
        """Parse all command line and config args of base and optional subclass

        This method first collects all the command line args to find the config
        file.  The config file must the "main" section for the base class.  If
        we are instantiating a subclass, the constructor must be supplied with a
        string for the name of the section in the config relevant to the base
        class.

        Next, this method reads in the config file all at once.  It parses the
        "main" section and the subclass section if the string if supplied.

        Finally, it overrides any parameters found in the config file with those
        supplied on the command-line.

        The subclass may optionally add command-line args and parameter defaults
        by overriding (and calling super() within) the following two methods:
            self.add_argparse_args()
            self.define_default_args()
            self.verify_frame(frame)
            self.on_message(frame)
        """

        # grab the command line args first so we can find the config file
        cmd_line_args = self.__parse_command_line_args()
        config_file_path = os.path.abspath(cmd_line_args['config_file'])
        logging.debug("config_file full path: " + config_file_path)

        # check to see that the file exists
        if not os.path.exists(config_file_path):
            raise ConfigException("Config file path is not valid")

        # parse the config file, and supply the subclass section
        config_args = self.__parse_config_file(config_file_path,
                                               subclass_section)

        # override config file values with command line parameters
        # only if command line values are defined
        for key in cmd_line_args:
            if cmd_line_args[key]:
                config_args[key] = cmd_line_args[key]

        # output final list of args
        logging.debug("Worker config parameters:")
        for key in config_args:
            logging.debug(key + ": " + str(config_args[key]))

        return config_args

    def add_argparse_args(self, parser):
        """Add arguments for argparse (OVERRIDE and call SUPER)

        This method can be overridden by a subclass in order to add
        command line arguments beyond what are in the base class.  The
        subclass MUST call the super version of this function in order
        to get these base class arguments.
        """
        # this "config" argument should be the only one with a default
        # all other defaults are added to ConfigParser, since
        # it will be overridden by command line args
        parser.add_argument("--config_file", "-c", dest="config_file",
                            help="configuration file")
        parser.add_argument("--apollo_host", "-a", dest="apollo_host",
                            help="Apollo server hostname or IP")
        parser.add_argument("--apollo_port", "-p", dest="apollo_port",
                            help="Apollo server port")
        parser.add_argument("--apollo_user", "-u", dest="apollo_user",
                            help="Apollo server username")
        parser.add_argument("--apollo_password", "-w", dest="apollo_password",
                            help="Apollo server password")
        parser.add_argument("--input_topic", "-i", dest="input_topic",
                            help="Subscribe to this topic for your input")
        parser.add_argument("--output_topic", "-o", dest="output_topic",
                            help="Publish any output to this topic by default")

    def __parse_command_line_args(self):
        parser = argparse.ArgumentParser()
        self.add_argparse_args(parser)
        args_dict = parser.parse_args().__dict__
        if ('config_file' not in args_dict or
            not args_dict['config_file']):
            parser.print_help()
            raise ConfigException("You must specify a config file")
        else:
            return args_dict

    def define_default_args(self):
        """Define the default values for config params (OVERRIDE and call SUPER)

        This method can be overridden by a subclass in order to add
        default values for the subclass section of the config file.  The
        subclass MUST call the super version of this function in order
        to get these base class defaults.
        """
        defaults = dict()
        defaults['apollo_host'] = "127.0.0.1"
        defaults['apollo_port'] = "61613"
        defaults['apollo_user'] = "admin"
        defaults['apollo_password'] = "password"
        return defaults

    def __parse_config_file(self, config_file_path, subclass_section=None):
        # get the config defaults
        defaults = self.define_default_args()

        config = ConfigParser.ConfigParser()
        config.read(config_file_path)
        config_dict = dict()

        # wish we could use ConfigParsers defaults parameters, but it always
        # returns defaults in its options() and items() functions. so we'll do
        # it ourselves...
        for default in defaults:
            config_dict[default] = defaults[default]

        # iterate through all config options and put in a dict
        base_options = config.options(BASE_SECTION)
        for option in base_options:
            value = config.get(BASE_SECTION, option)
            # convert to real bool if it is
            value = check_for_bool(value)
            config_dict[option] = value

        # iterate through subclass options if specified
        if subclass_section:
            try:
                sub_options = config.options(subclass_section)
                for option in sub_options:
                    # prevent the subclass from using config params of the
                    # base class
                    if option in base_options:
                        raise ConfigException("Your subclass is trying to reuse a config"
                                              " file option of the base class")
                    value = config.get(subclass_section, option)
                    # convert to real bool if it is
                    value = check_for_bool(value)
                    config_dict[option] = value
            except ConfigParser.NoSectionError:
                logging.error("Your config does not have a '{0}' section"
                              " for your Worker subclass!".format(subclass_section))
                raise

        return config_dict

    def run(self):
        with ApolloConnection(self.args) as self.apollo_conn:
            # subscribe to topic and handle messages;
            #  otherwise, just end and let something override run()
            if "input_topic" in self.args and self.args['input_topic']:
                while True:
                    frame = self.apollo_conn.receiveFrame()
                    logging.info("Received message: {0}".format(frame.info()))
                    try:
                        self.on_message(frame)
                    # skip over bad frames, but halt on other exceptions
                    except FrameException, e:
                        logging.exception(e)
            else:
                logging.warning("No input topic was specified, so unless this"
                                " function is overridden, nothing will happen")

    def on_message(self, frame):
        """Handles incoming messages and runs operations (OVERRIDE and SUPER)

        This method is designed to be overridden (call super first!) with
        additional operations to handle messages.

        If the message received expects a reply, a transaction will be recorded,
        with the reply-to destination tracked.  If, before replying, this worker
        needs to publish and receive a response, those elements will be recorded
        linked to this transaction.

        When you override this method (which is essentially a requirements), you
        should check that your frame header destination is what you expect so
        that you can filter out replies on temp-queues.  Otherwise, you'll
        accidentally call self.on_message() for replies the same you would for
        original messages.

        Returns a transaction so that you may modify it in the base class and
        optionally pass it into any secondary publish calls.
        """
        # must ack to remove from queue
        self.apollo_conn.ack(frame)

        # check if this is something you need to reply to, and create a
        #  a transaction if so; otherwise, transaction is None
        transaction_uuid = None
        if 'reply-to' in frame.headers:
            transaction_uuid = str(UUID())
            self.transactions[transaction_uuid] = {'reply-to': frame.headers['reply-to']}
            logging.debug("GOT A TRANSACTION")
            logging.debug(transaction_uuid)
            logging.debug(self.transactions[transaction_uuid])

        # Raise FrameException if frame is bad
        try:
            self.verify_frame(frame)
            # check if this is a reply you're waiting for
            if frame.headers['destination'].startswith('/queue/temp'):
                # the destination we used to subscribe looks a little different
                #  than the destination coming in this time; hence, the weird
                #  tuple check with string concatentation below.
                transaction = str(frame.headers['destination'].split('.')[-1])
                logging.debug("GOT OUR SECONDARY RESPONSE")
                logging.debug(transaction)
                try:
                    temp_sub = self.transactions[transaction]['temp_sub']
                    self.apollo_conn.unsubscribe(temp_sub)
                    logging.debug("UNSUBSCRIBING FROM SECONDARY SUB")
                    logging.debug(temp_sub)
                except KeyError, ValueError:
                    logging.error("Somehow you got a message on a temp queue"
                                  " that you weren't keeping track of."
                                  " That is very weird so let's cut our losses.")
                    raise
                self.handle_reply(frame, transaction)
        except FrameException, e:
            # Frame not verified; send an error in reply (if expected)
            #  otherwise, just skip it and continue outside loop...
            #TODO: test this
            if 'reply-to' in frame.headers:
                self.reply({ 'Error': 'Frame failed verification' }, frame.headers['reply-to'])
            raise

        # returning transaction ID for handling in your reply
        return transaction_uuid

    def handle_reply(self, frame, transaction=None):
        """Handles a reply over a temp queue to a request you already submitted

        If a transaction is provided with a valid callback function, we'll
        try to call the function, but we do not guarantee that it exists.
        """
        #TODO: test the error cases here
        if transaction:
            callback = self.transactions[transaction]['callback']
            destination = self.transactions[transaction]['reply-to']
            logging.debug("SEND BACK TO {}".format(destination))
            if (callback
                and hasattr(callback, '__name__')
                and hasattr(callback, '__call__')
                and callback.__name__ in dir(self)):
                logging.debug("RUNNING CALLBACK WITH {}".format(destination))
                callback(frame, destination)
            elif not callback:
                #No callback is fine, we just won't do anything
                pass
            else:
                raise WetwareException("Invalid callback provided: {0}".format(callback))

    def verify_frame(self, frame):
        """Verify a frame (OVERRIDE and SUPER)

        Verify that a frame is valid JSON and has the appropriate fields.
        This function may be overrided by a subclass to add to the verification
        but it must call the SUPER() first.

        Returns True/False when validation passes/fails.
        """
        try:
            message = json.loads(frame.body)
            #handle "operation" messages for sync and async commands
            if ('operation' in message and
                message['operation'].startswith('command')):
                if 'command' not in message:
                    raise FrameException({'message': "Received a 'command' operation"
                                           " without a 'command' field",
                                           'info': frame.info(),
                                           'body': frame.body})
                if message['operation'] not in ('command_sync',
                                                'command_async'):
                    raise FrameException({'message': "Received an unknown 'command' operation",
                                           'info': frame.info(),
                                           'body': frame.body})
        except ValueError:
            # raising FrameException so we can skip it--this shouldn't be fatal
            raise FrameException({'message': "Received an invalid JSON object in message",
                                   'info': frame.info(),
                                   'body': frame.body})

    """Publish a message to a topic using your Apollo Connection

    If no topic is supplied, we assume you want to publish output to the
    topic you configured with your OUTPUT_TOPIC parameter in your config
    file. You know, cause we're nice.

    Setting expect_reply to True establishes a subscription to a temp-queue
    for your response.  When you get the response, this worker will call
    self.handle_reply() to handle it, and the worker will unsubscribe from
    the temp queue.

    Returns False if you never specified an OUTPUT_TOPIC.
    """
    def publish(self, message, topic=None, expect_reply=False, callback=None, transaction=None):
        # If you pass a dict, we'll convert it to JSON for you
        if isinstance(message, dict):
            message_str = json.dumps(message)
        # Otherwise, we'll try to cast whatever you passed as a string
        else:
            message_str = str(message)

        # Hopefully you've initialized your Apollo connection via run()
        if self.apollo_conn:
            # If no topic is provided, use the output_topic from config file
            if not topic:
                # But, of course, make sure there is one in the config
                # If not, return early
                if 'output_topic' not in self.args:
                    raise ConfigException("Tried to publish a message but there is no"
                                    " output_topic specified in the config!")
                else:
                    topic = self.args['output_topic']
            # Just check to see if we've specified a topic at this point.  This
            # is totally redundant, but feels safer.
            if topic:
                if expect_reply:
                    #use UUID from prior transaction, or make one here
                    if transaction:
                        logging.debug("PUBLISHING BASED ON TRANSACTION {}".format(transaction))
                        temp_uuid = transaction
                    else:
                        logging.debug("PUBLISHING WITH BRAND NEW TRANSACTION!")
                        temp_uuid = str(UUID())
                        #this will already exist if we started a transaction
                        if temp_uuid not in self.transactions:
                            self.transactions[temp_uuid] = {}
                    # self.reply_subs.append(
                    #     self.apollo_conn.subscribe('/temp-queue/' + temp_uuid,
                    #                                {StompSpec.ACK_HEADER:
                    #                                 StompSpec.ACK_CLIENT_INDIVIDUAL}))
                    # if callback:
                    #     self.reply_callbacks.append(callback)
                    # else:
                    #     self.reply_callbacks.append(None)
                    temp_sub = self.apollo_conn.subscribe('/temp-queue/' + temp_uuid,
                                                          {StompSpec.ACK_HEADER:
                                                           StompSpec.ACK_CLIENT_INDIVIDUAL})
                    self.transactions[temp_uuid]['callback'] = callback
                    self.transactions[temp_uuid]['temp_sub'] = temp_sub
                    logging.debug("HERES OUR MAP")
                    logging.debug(self.transactions[temp_uuid])
                    self.apollo_conn.send(topic, message_str,
                                          headers={'reply-to': '/temp-queue/' + temp_uuid})
                else:
                    self.apollo_conn.send(topic, message_str)
        else:
            logging.warning("Tried to publish a message but there is no Apollo"
                            " connection! (Did you call run() on your Worker?)")

    def reply(self, message, destination):
        """Send a reply to the last person who was expecting it.

        Call this after you've received a message expecting a reply and you've
        done the work to send in the reply.  This takes the longest-waiting
        reply topic out of the queue, so make sure you're replying to things
        in order!
        """
        try:
            self.publish(message, destination)
            #remove the transaction from our map
            if destination in self.transactions:
                del self.transactions[destination]
        except IndexError:
            logging.warning("Tried to reply when no one was expecting a reply!"
                            " Be careful: whatever you're doing may cause you"
                            " to reply to the wrong thing in the future!")

def check_for_bool(value):
    if value.lower() == 'true':
        return True
    elif value.lower() == 'false':
        return False
    else:
        return value

def run_command(command_args, sync=False, log_file=None, cwd=None):
    """Runs a command synchronously or asynchronously

    subprocess runs async by default.  Sync is achieved by waiting
    for stdout and stderr.

    Logs output if log_file is supplied; otherwise, does not track it.

    Returns the process exit status if sync.
    Returns the pid if async. Output from async command is not recovered if not
    logged to a file.

    Processes should exit if Python terminates.
    """
    logging.info("Running command: {0}".format(' '.join(command_args)))
    if log_file:
        logging.info("Command output logging to: {0}".format(log_file))
        with open(log_file,'a') as log_file:
            proc = subprocess.Popen(command_args,
                                    stdout=log_file,
                                    stderr=subprocess.STDOUT,
                                    cwd=cwd)
    else:
        proc = subprocess.Popen(command_args,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                cwd=cwd)
    if sync:
        stdout, stderr = proc.communicate()
        if stdout:
            logging.debug("stdout: {0}".format(stdout))
        if stderr:
            logging.warning("stderr: {0}".format(stderr))
        ret_code = proc.returncode
        logging.info("command_sync process exited with status: "
                     "{0}".format(ret_code))
        return ret_code
    else:
        pid = proc.pid
        logging.info("command_async process is running at pid: "
                     "{0}".format(pid))
        return pid

class ApolloConnection(object):
    def __init__(self, args):
        self.args = args

    def __enter__(self):
        self.apollo_conn = Stomp(
            StompConfig('tcp://{0}:{1}'.format(self.args['apollo_host'],
                                               self.args['apollo_port']),
                                               self.args['apollo_user'],
                                               self.args['apollo_password']))
        self.apollo_conn.connect()
        if self.args.get('input_topic'):
            logging.info("Subscribing to {0}".format(self.args['input_topic']))
            self.apollo_conn.subscribe(self.args['input_topic'],
                                       {StompSpec.ACK_HEADER:
                                        StompSpec.ACK_CLIENT_INDIVIDUAL})
        return self.apollo_conn

    def __exit__(self, type, value, tb):
        logging.info("Closing connection to {0}:{1}".format(
            self.args['apollo_host'],
            self.args['apollo_port']))
        self.apollo_conn.disconnect()

class WetwareException(Exception):
    pass

class ConfigException(WetwareException):
    pass

class FrameException(WetwareException):
    pass
