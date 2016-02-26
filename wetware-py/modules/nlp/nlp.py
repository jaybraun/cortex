#!/usr/bin/env python

import logging
import json
import sys

from wetware.worker import Worker
from wetware.worker import WetwareException
from wetware.worker import FrameException

class WetwareWorker(Worker):

    def __init__(self, subclass_section):
        super(WetwareWorker, self).__init__(subclass_section)

    def on_message(self, frame):
        try:
            ### This header must not be modified ###
            super(WetwareWorker, self).on_message(frame)
            message = json.loads(frame.body)
            ############## End header ##############

            #TODO throw out replies in the super class
            if frame.headers['destination'] == self.args['neuron_topic']:
                self.process_neuron_operation(message)
            elif frame.headers['destination'] == self.args['nlp_topic']:
                self.process_nlp_statement(message)
        except:
            self.reply({'responses': "I'm terribly sorry.  I'm feeling faint.  Perhaps I should see a doctor..."})
            logging.exception("Caught Exception:")

    def process_nlp_statement(self, message):
        for statement in message['statements']:
            if '?' in statement:
                self.parse_interrogative_statement(statement)
            else:
                self.parse_indicative_statement(statement)

    def parse_interrogative_statement(self, statement):
        words = statement.split(' ')
        if words[0] == 'Does':
            self.parse_question_does(words)
        elif words[0] == 'Where':
            self.parse_question_where(words)
        elif words[0] == 'Is':
            self.parse_question_is(words)
        elif words[0] == 'What':
            self.parse_question_what_is_the(words)
        else:
            self.reply({'responses': "I'm terribly sorry, but I don't understand the question."})

    def parse_question_does(self, words):
        try:
            does = words[0] #will disregard this
            subj = words[1].strip()
            pred = words[2].strip() + 's' #add back indicative verb conj 's'
            obj = words[3].strip()[:-1] #take off the question mark
            output_data = {'statements': []}
            output_data['statements'].append(self.compose_gremlin_statement('g.V().has("name","' + subj + '").both("' + pred + '").has("name","' + obj + '")'))
            output_data['statements'].append(self.compose_gremlin_statement('g.V().has("name","' + subj + '").both("' + pred + '").both("' + pred + '").simplePath().has("name","' + obj + '")'))
            output_data['statements'].append(self.compose_gremlin_statement('g.V().has("name","' + subj + '").both("' + pred + '").both("' + pred + '").both("' + pred + '").simplePath().has("name","' + obj + '")'))
            self.publish(output_data, expect_reply=True, callback=self.interpret_does_response)
        except:
            self.reply({'responses': "I'm terribly sorry, but I don't understand the question."})
            logging.exception("Caught Exception:")

    def parse_question_is(self, words):
        try:
            is_word = words[0] #will disregard this
            subj = words[1].strip()
            key = words[2].strip()[:-1]
            output_data = {'statements': []}
            output_data['statements'].append(self.compose_gremlin_statement(
                'g.V().has("name","' + subj + '").values("' + key + '")'))
            self.publish(output_data, expect_reply=True, callback=self.interpret_audrey_is)
        except:
            self.reply({'responses': "I'm terribly sorry, but I don't understand the question."})
            logging.exception("Caught Exception:")

    def parse_question_what_is_the(self, words):
        try:
            logging.debug(words)
            #0,1,2 What is the
            key = words[3].strip()
            #4 of
            obj = words[5].strip()[:-1]
            output_data = {'statements': []}
            output_data['statements'].append(self.get_vertex_property_statement(obj, key))
            self.publish(output_data, expect_reply=True, callback=self.interpret_audrey_what_is_the)
        except:
            self.reply({'responses': "I'm terribly sorry, but I don't understand the question."})
            logging.exception("Caught Exception:")

    #TODO: this is broken
    def parse_question_where(self, words):
        try:
            #0,1 Where is
            subj = words[2].strip()[:-1]
            output_data = {'statements': []}
            output_data['statements'].append(self.get_vertex_property_statement(subj, "location"))
            self.publish(output_data, expect_reply=True, callback=self.interpret_audrey_where)
        except:
            self.reply({'responses': "I'm terribly sorry, but I don't understand the question."})
            logging.exception("Caught Exception:")

    def parse_indicative_statement(self, statement):
        words = statement.split(' ')
        output_data = {'statements': []}
        try:
            subj = words[0].strip()
            pred = words[1].strip()
            obj = words[2].strip()
            #take out the period
            if '.' in obj:
                obj = obj[:-1]
            if pred == "is":
                #"is" will become a boolean property on node
                output_data['statements'].append(self.add_vertex_property_statement(subj, obj, True))
            else:
                #otherwise, add nodes and edge (add_edge adds nodes and edge)
                output_data['statements'].append(self.add_edge_statement(subj, obj, pred))
            self.publish(output_data, expect_reply=True, callback=self.acknowledge_response)
        except:
            self.reply({'responses': "I'm having trouble understanding what it is you want to say..."})
            logging.exception("Caught Exception:")

    def add_vertex_statement(self, *names):
        statement = {'fxns': [], 'api': 'neuron'}
        for name in names:
            fxn = {'fxn': 'addVertex', 'name': name}
            statement['fxns'].append(fxn)
        return statement

    def add_edge_statement(self, from_vertex, to_vertex, label):
        statement = {'fxns': [], 'api': 'neuron'}
        fxn = {'fxn': 'addEdge',
               'fromVertex': from_vertex,
               'toVertex': to_vertex,
               'label': label }
        statement['fxns'].append(fxn)
        return statement

    def add_vertex_property_statement(self, name, prop_name, prop_value):
        statement = {'fxns': [], 'api': 'neuron'}
        fxn = {'fxn': 'addVertexProperty',
               'name': name,
               'property': prop_name,
               'value': prop_value }
        statement['fxns'].append(fxn)
        return statement

    def get_vertex_property_statement(self, name, prop_name):
        statement = {'fxns': [], 'api': 'neuron'}
        fxn = {'fxn': 'getVertexProperty',
               'name': name,
               'property': prop_name }
        statement['fxns'].append(fxn)
        return statement

    def acknowledge_response(self, frame):
        #TODO: clean this up
        reply = {'responses': ""}
        try:
            responses = json.loads(frame.body)['responses']
            for response in responses:
                if not response:
                    reply['responses'] = "Hmm, apologies...I've...lost my train of thought..."
            reply['responses'] = "Alright, then.  I'll note that."
        except KeyError, ValueError:
            reply['responses'] = "Hmm, apologies...I've...lost my train of thought..."
            logging.exception("Caught Exception:")
        self.reply(reply)

    def compose_raw_statement(self, statement):
        output_statement = {'fxns': []}
        for input_function in statement.split('.'):
            #these are the Tinker/TitanGraphs or traversal()
            # their usage is hardcoded at neuron
            if input_function == 'graph' or input_function == 'g':
                continue
            else:
                function_name = input_function.split('(')[0]
                arguments = []
                for argument in input_function.split('(')[1].split(')')[0].split(','):
                    #don't put in empty strings
                    if argument:
                        #strip whitespace, and strip quotes (on each side)
                        # there would be a problem here is quotes weren't there
                        arguments.append(argument.strip()[1:-1])
                output_function = {
                    'fxn': function_name,
                    'args': arguments
                }
                output_statement['fxns'].append(output_function)
        return output_statement

    def process_neuron_operation(self, input_message):
        output_data = { 'statements': []}
        for raw_statement in input_message['statements']:
            if "addVertex" in raw_statement or 'addEdge' in raw_statement:
                output_data['statements'].append(self.compose_blueprints_statement(raw_statement))
            else:
                output_data['statements'].append(self.compose_gremlin_statement(raw_statement))
        logging.debug(output_data)
        self.publish(output_data, expect_reply=True)

    def compose_addedge_statement(self, raw_statement):
        #when neuron sees it's blueprints, it will check if fxn is addEdge
        # and handle this different api accordingly
        output_statement = {'fxns': []}
        addedge_statement = {}
        #format: Vertex.addEdge(label, Vertex, key, value, ... )
        # so, everything before .addEdge is the fromVertex Gremlin
        fromGremlin = raw_statement.split('.addEdge(')[0]
        # the label is the first comma-separated argument inside .addEdge()
        label = raw_statement.split('.addEdge(')[1].split(',')[0].strip()[1:-1]
        # properties are all strings from the end of the function ')'
        #  to the end of the toGremlin function, which also ends in ')'
        properties = []
        for prop in raw_statement.split(')')[-2].split(','):
            if prop:
                properties.append(prop.strip()[1:-1])
        # grab everything after 'label'
        #  start at g.V
        #  end at second instance (in reverse) of ')'
        toGremlinMess = raw_statement.split(label)[1]
        beginToGremlin = toGremlinMess.find('g.V')
        endToGremlin = toGremlinMess.rfind(')', 0, len(toGremlinMess) - 1) + 1
        toGremlin = toGremlinMess[beginToGremlin:endToGremlin]
        # wrap them with a bow
        addedge_statement['fxn'] = 'addEdge'
        addedge_statement['fromVertex'] = self.compose_raw_statement(fromGremlin)
        addedge_statement['toVertex'] = self.compose_raw_statement(toGremlin)
        addedge_statement['label'] = label
        addedge_statement['properties'] = properties
        output_statement['fxns'].append(addedge_statement)
        return output_statement

    def compose_blueprints_statement(self, raw_statement):
        #addEdge is a special case, addVertex is not (and don't expect others to be)
        if 'addEdge' in raw_statement:
            statement = self.compose_addedge_statement(raw_statement)
        else:
            statement = self.compose_raw_statement(raw_statement)
        statement['api'] = 'blueprints'
        return statement

    def compose_gremlin_statement(self, raw_statement):
        #no special cases for Gremlin
        statement = self.compose_raw_statement(raw_statement)
        statement['api'] = 'gremlin'
        return statement

    def interpret_audrey_is(self, frame):
        reply = {}
        responses = json.loads(frame.body)['responses']
        if responses[0]:
            reply['responses'] = "Yes, I do believe so."
        else:
            reply['responses'] = "No, I don't believe that's true."
        self.reply(reply)

    def interpret_audrey_where(self, frame):
        reply = {}
        responses = json.loads(frame.body)['responses']
        location = responses[0]
        #TODO: this empty list parsing needs to change
        if location and location != "[]":
            reply['responses'] = "Why it's right at {0}.".format(location)
        else:
            reply['responses'] = "You know, I don't know where it is!"
        self.reply(reply)

    def interpret_audrey_what_is_the(self, frame):
        reply = {}
        responses = json.loads(frame.body)['responses']
        value = responses[0]
        if value:
            reply['responses'] = "It appears to be {0}.".format(value)
        else:
            reply['responses'] = "You know, I'm just not sure."
        self.reply(reply)

    def interpret_does_response(self, frame):
        #interpret response
        #respond to UI
        # if first answer if yes, conf = 1.0
        #  if second answer is yes, conf = 0.5
        #  if third answer is yes, conf = 0.25
        reply = {}
        try:
            responses = json.loads(frame.body)['responses']
            if len(responses) == 1:
                reply['responses'] = "Alright, then.  I'll note that."
            elif len(responses) == 3:
                if "OK" in responses:
                    reply['responses'] = "Alright, then.  I'll note that."
                elif responses[0]:
                    reply['responses'] = "Yes, most certainly."
                elif responses[1]:
                    reply['responses'] = "I think so, but I can't be sure."
                elif responses[2]:
                    reply['responses'] = "I suppose it's possible, but I doubt it."
                else:
                    reply['responses'] = "No, I don't believe so."
            else:
                reply['responses'] = "I'm terribly sorry.  I'm not sure how to answer that."
        except KeyError, ValueError:
            reply['responses'] = "Hmm, apologies...I've...lost my train of thought..."
            logging.exception("Caught Exception:")
        self.reply(reply)

    def define_default_args(self):
        ### This header must not be modified ###
        defaults = super(WetwareWorker, self).define_default_args()
        ############## End header ##############

        #defaults['my_parameter'] = "my_default_parameter_value"

        ### This footer must not be modified ###
        return defaults
        ############## End footer ##############

    def add_argparse_args(self, parser):
        ### This headermust not be modified ###
        super(WetwareWorker, self).add_argparse_args(parser)
        ############## End header ##############

        #parser.add_argument("--my_parameter", "-m", dest="my_parameter",
        #                    help="this is my new, special parameter")

    def verify_frame(self, frame):
        ### This header must not be modified ###
        super(WetwareWorker, self).verify_frame(frame)
        message = json.loads(frame.body)
        ############## End header ##############

        if frame.headers['destination'].startswith('/queue/temp'):
            for key in ['responses']:
                if key not in message:
                    raise FrameException("Message has no {0} field".format(key))
        else :
            for key in ['statements']:
                if key not in message:
                    raise FrameException("Message has no {0} field".format(key))

def main():
    logging.basicConfig(level=logging.DEBUG)
    wetware_worker = WetwareWorker("wetware")
    wetware_worker.run()

if __name__ == "__main__":
    main()
