#!/usr/bin/env python

import logging
import json
import time

from wetware.worker import Worker
from wetware.worker import ApolloConnection

class WetwareWorker(Worker):

    def run(self):
        with ApolloConnection(self.args) as self.apollo_conn:
            #this object is getting overloaded to handle all cases (not minimal set)
            incident = {'incident_id': 'My new incident',
                        'user': {
                            'name': 'David Horres',
                        }}
            self.publish(incident, topic='/queue/wetware.ngfr.register.new', callback=self.ack)
            self.wait_for_response() #ack
            time.sleep(3)
            self.publish(incident, topic='/queue/wetware.ngfr.register.join', callback=self.ack)
            self.wait_for_response() #ack
            time.sleep(1)
            self.wait_for_response() #alert1
            self.wait_for_response() #alert2
            time.sleep(5)
            self.publish(incident, topic='/queue/wetware.ngfr.register.close', callback=self.ack)
            self.wait_for_response() #ack

    def wait_for_response(self):
        while True:
            frame = self.apollo_conn.receiveFrame()
            message = json.loads(frame.body)
            if 'alert_topics' in message:
                for topic in message['alert_topics']:
                    self.subscribe(topic)
            logging.info("Received message: {0}".format(frame.info()))
            logging.info(frame.body)
            self.on_message(frame)
            break

    def ack(self, frame, context, transaction):
        logging.debug(json.loads(frame.body))

def main():
    logging.basicConfig(level=logging.INFO)
    wetware_worker = WetwareWorker("wetware")
    wetware_worker.run()

if __name__ == "__main__":
    main()
