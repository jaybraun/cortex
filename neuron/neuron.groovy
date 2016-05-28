import java.net.SocketTimeoutException;

import org.apache.activemq.transport.stomp.Stomp.Headers.Subscribe;
import org.apache.activemq.transport.stomp.StompConnection;
import org.apache.activemq.transport.stomp.StompFrame;

public class Neuron {
    public static final Logger logging = Logger.getRootLogger();

    //public static final String NEURON_HOME = System.getenv("NEURON_HOME");
    //public static final String AUDREY_CONF_PATH = NEURON_HOME + "/conf/audrey.properties";
    public static final String AUDREY_CONF_PATH = "conf/audrey.properties";

    public static final String APOLLO_HOSTNAME = "cortex-apollo";
    public static final int APOLLO_PORT = 61613;
    public static final String APOLLO_USERNAME = "admin";
    public static final String APOLLO_PASSWORD = "password";
    public static final String INPUT_DESTINATION = "/queue/neuron.operation";

    public StompConnection connection;
    public graph;
    public g;

    public reply_topics = [];

    public Neuron() { };

    public void initialize() throws Exception {
        graph = TitanFactory.open(AUDREY_CONF_PATH);
        g = graph.traversal();
        connection = new StompConnection();
        connection.open(APOLLO_HOSTNAME, APOLLO_PORT);
        connection.connect(APOLLO_USERNAME, APOLLO_PASSWORD);
        connection.subscribe(INPUT_DESTINATION, Subscribe.AckModeValues.CLIENT);
    }

    public executeStatement(statement) {
        def api = statement['api'];
        if (statement['fxns'].size() < 1) {
            logging.warn("Received Neuron statement with no function calls");
            return [];
        } else if (api == "blueprints") {
            return executeBlueprintsStatement(statement);
        } else if (api == "gremlin") {
            return executeGremlinStatement(statement);
        } else if (api == "neuron") {
            return executeNeuronStatement(statement);
        }
    }

    public executeNeuronStatement(statement) {
    /*This will return the result of whatever the LAST function is, and nothing
      in between.  And that's normally what we want; otherwise, you should
      divide the functions into different statements. */
        def fxns = statement['fxns'];
        def retVal = "";
        fxns.each {
            switch (it['fxn']) {
            case "addVertex":
                retVal = neuronAddVertex(it['name']);
                break;
            case "addVertexProperty":
                retVal = neuronAddVertexProperty(it['name'],it['property'],it['value']);
                break;
            case "getVertexProperty":
                retVal = neuronGetVertexProperty(it['name'],it['property']);
                break;
            case "addEdge":
                retVal = neuronAddEdge(it['fromVertex'],it['toVertex'],it['label']);
                break;
            case "getVerticesTypeGeoWithin":
                retVal = neuronGetVerticesTypeGeoWithin(it['type'],it['property'],it['geoshape']);
                break;
            }
        }
        return retVal;
    }

    public neuronAddVertex(name) {
        def vertex_iter = g.V().has("name", name);
        if (vertex_iter) {
            return vertex_iter.next();
        } else {
            return graph.addVertex("name", name);
        }
    }

    public neuronAddVertexProperty(name, key, value) {
    /*The only types supported in Neuron will be:
      int, double, string, and Geoshape (using list [])
      Actual lists should be handled by Neuron libraries as
      multiple property values under the same property key.
    */
        def vertex = neuronAddVertex(name);
        println "Adding property: " + key;
        switch(value.getClass()) {
        case String:
            if (key == "type") {
                vertex.property(key, value);
            } else {
                //we could Base64 encode everything, but we'll just push
                // that responsibility to clients.  Invalid chars are:
                // '[',  ']', and ','
                //vertex.property(key, "base64:" + value.bytes.encodeBase64().toString());

                //instead just do it like everything else
                vertex.property(key, value);
            }
            break;
        case Integer:
            //this actually works as is, but might as well separate
            vertex.property(key, value);
            break;
        case BigDecimal:
            vertex.property(key, value.doubleValue());
            break;
        case ArrayList:
            //Expect ArrayLists to be mapped to Geoshapes.
            // This requires a property defined in the schema typed as Geoshape
            // If this isn't the case, this add() will fail (look at exception)
            vertex.property(key, value);
            break;
        default:
            vertex.property(key, value);
            break;
        }
        println "Property added: " + value.toString();
        return vertex;
    }

    public neuronGetVertexProperty(name, key) {
        def prop_iter = g.V().has("name", name).values(key);
        if (prop_iter) {
            return prop_iter.next();
        } else {
            return "";
        }
    }

    public neuronAddEdge(fromName, toName, label) {
    //Adding an Edge will add the Vertices as well
        def fromVertex = neuronAddVertex(fromName);
        def toVertex = neuronAddVertex(toName);
        def edge_iter = g.V(fromVertex).out(label).has("name", toName);
        if (edge_iter) {
            return edge_iter.next();
        } else {
            return fromVertex.addEdge(label, toVertex);
        }
    }

    public neuronGetVerticesTypeGeoWithin(type, property, geoshape) {
        if (geoshape.size == 3) {
            return g.V().has("type", type).has(property, geoWithin(Geoshape.circle(geoshape[0],geoshape[1],geoshape[2]))).valueMap().toList();
        } else if (geoshape.size == 4) {
            return g.V().has("type", type).has(property, geoWithin(Geoshape.box(geoshape[0],geoshape[1],geoshape[2],geoshape[3]))).valueMap().toList();
        } else {
            return "";
        }
    }

    public executeBlueprintsStatement(statement) {
        def fxns = statement['fxns'];
        if (fxns.size() > 1) {
            logging.warn("Neuron can currently only process one Blueprints function at a time");
            return [];
        } else {
            def fxn = fxns[0];
            if (fxn['fxn'] == "addEdge") {
                def fromVertex = executeGremlinStatement(fxn['fromVertex']);
                def toVertex = executeGremlinStatement(fxn['toVertex']);
                def label = fxn['label']
                def properties = fxn['properties'];
                return fromVertex.addEdge(label, toVertex, *properties);
            } else {
                return graph."${fxns[0]['fxn']}"(*fxns[0]['args']);
            }
        }
    }

    public executeGremlinStatement(statement) {
        def fxns = statement['fxns'];
        if (fxns.size() > 10) {
            logging.warn("Neuron can not process Gremlin operations with greater than 10 linked calls");
        } else if (fxns.size() == 1) {
            return g."${fxns[0]['fxn']}"(*fxns[0]['args']);
        } else if (fxns.size() == 2) {
            return g."${fxns[0]['fxn']}"(*fxns[0]['args'])."${fxns[1]['fxn']}"(*fxns[1]['args']);
        } else if (fxns.size() == 3) {
            return g."${fxns[0]['fxn']}"(*fxns[0]['args'])."${fxns[1]['fxn']}"(*fxns[1]['args'])."${fxns[2]['fxn']}"(*fxns[2]['args']);
        } else if (fxns.size() == 4) {
            return g."${fxns[0]['fxn']}"(*fxns[0]['args'])."${fxns[1]['fxn']}"(*fxns[1]['args'])."${fxns[2]['fxn']}"(*fxns[2]['args'])."${fxns[3]['fxn']}"(*fxns[3]['args']);
        } else if (fxns.size() == 5) {
            return g."${fxns[0]['fxn']}"(*fxns[0]['args'])."${fxns[1]['fxn']}"(*fxns[1]['args'])."${fxns[2]['fxn']}"(*fxns[2]['args'])."${fxns[3]['fxn']}"(*fxns[3]['args'])."${fxns[4]['fxn']}"(*fxns[4]['args']);
        } else if (fxns.size() == 6) {
            return g."${fxns[0]['fxn']}"(*fxns[0]['args'])."${fxns[1]['fxn']}"(*fxns[1]['args'])."${fxns[2]['fxn']}"(*fxns[2]['args'])."${fxns[3]['fxn']}"(*fxns[3]['args'])."${fxns[4]['fxn']}"(*fxns[4]['args'])."${fxns[5]['fxn']}"(*fxns[5]['args']);
        } else if (fxns.size() == 7) {
            return g."${fxns[0]['fxn']}"(*fxns[0]['args'])."${fxns[1]['fxn']}"(*fxns[1]['args'])."${fxns[2]['fxn']}"(*fxns[2]['args'])."${fxns[3]['fxn']}"(*fxns[3]['args'])."${fxns[4]['fxn']}"(*fxns[4]['args'])."${fxns[5]['fxn']}"(*fxns[5]['args'])."${fxns[6]['fxn']}"(*fxns[6]['args']);
        } else if (fxns.size() == 8) {
            return g."${fxns[0]['fxn']}"(*fxns[0]['args'])."${fxns[1]['fxn']}"(*fxns[1]['args'])."${fxns[2]['fxn']}"(*fxns[2]['args'])."${fxns[3]['fxn']}"(*fxns[3]['args'])."${fxns[4]['fxn']}"(*fxns[4]['args'])."${fxns[5]['fxn']}"(*fxns[5]['args'])."${fxns[6]['fxn']}"(*fxns[6]['args'])."${fxns[7]['fxn']}"(*fxns[7]['args']);
        } else if (fxns.size() == 9) {
            return g."${fxns[0]['fxn']}"(*fxns[0]['args'])."${fxns[1]['fxn']}"(*fxns[1]['args'])."${fxns[2]['fxn']}"(*fxns[2]['args'])."${fxns[3]['fxn']}"(*fxns[3]['args'])."${fxns[4]['fxn']}"(*fxns[4]['args'])."${fxns[5]['fxn']}"(*fxns[5]['args'])."${fxns[6]['fxn']}"(*fxns[6]['args'])."${fxns[7]['fxn']}"(*fxns[7]['args'])."${fxns[8]['fxn']}"(*fxns[8]['args']);
        } else if (fxns.size() == 10) {
            return g."${fxns[0]['fxn']}"(*fxns[0]['args'])."${fxns[1]['fxn']}"(*fxns[1]['args'])."${fxns[2]['fxn']}"(*fxns[2]['args'])."${fxns[3]['fxn']}"(*fxns[3]['args'])."${fxns[4]['fxn']}"(*fxns[4]['args'])."${fxns[5]['fxn']}"(*fxns[5]['args'])."${fxns[6]['fxn']}"(*fxns[6]['args'])."${fxns[7]['fxn']}"(*fxns[7]['args'])."${fxns[8]['fxn']}"(*fxns[8]['args'])."${fxns[9]['fxn']}"(*fxns[9]['args']);
        }
    }

    public void onMessage(StompFrame frame) {
        if (frame.headers.containsKey('reply-to')) {
            //NOTE: pop comes from the end, so we're inserting at the front
            reply_topics.putAt(0, frame.headers['reply-to']);
        }
        try {
            connection.ack(frame);
            def parser = new JsonSlurper();
            def message = parser.parseText(frame.getBody());
            //return the result of each Statement (but not of each function)
            def reply = ["statements": []];
            for (statement in message['statements']) {
                println statement;
                def result;
                try {
                    result = executeStatement(statement);
                    if (statement["api"] == "gremlin"){
                        result = result.toList();
                    }
                } catch (Exception e) {
                    logging.warn("NeuronException executing statement: " + statement);
                    logging.warn(e.toString());
                    logging.warn(e.getMessage());
                    logging.warn(e.getStackTrace());
                    result = "";
                }
                reply["statements"].add(result.toString());
                g.tx().commit();
            }
            if (reply_topics.size() > 0) {
                //NOTE: pop comes from the end, so we're inserting at the front
                def dest = reply_topics.pop();
                println "Sending reply:";
                println reply;
                connection.send(dest, new JsonBuilder(reply).toString());
            }
        } catch (JsonException e) {
            logging.warn("Neuron received invalid JSON message");
            connection.send(dest, new JsonBuilder(reply).toString());
        } catch (Exception e) {
            e.printStackTrace();
            logging.warn("Neuron failed to run operation; probably invalid Gremlin");
            connection.send(dest, new JsonBuilder(reply).toString());
        }
    }

    //Creates property keys for 'name', 'type', and 'location'
    //Creates composite index on 'name', and 'name'+'type'
    //Creates mixed index on 'name', 'type', and 'location'
    public void initializeIndexing() {

        //can't seem to add indexes in a separate transaction from when creating
        // the property keys, so we'll do it altogether
        //This only checks to see if 'name' was created, so incomplete setups
        // will not setup correctly on subsequent runs
        def mgmt = graph.openManagement();
        if (! mgmt.containsPropertyKey('name')) {
            def name = mgmt.makePropertyKey('name').dataType(String.class).cardinality(Cardinality.SINGLE).make();
            def type = mgmt.makePropertyKey('type').dataType(String.class).cardinality(Cardinality.SINGLE).make();
            def location = mgmt.makePropertyKey('location').dataType(Geoshape.class).make();
            mgmt.buildIndex('byNameComposite', Vertex.class).addKey(name).buildCompositeIndex();
            mgmt.buildIndex('byTypeComposite', Vertex.class).addKey(type).buildCompositeIndex();
            mgmt.buildIndex('byNameTypeComposite', Vertex.class).addKey(name).addKey(type).buildCompositeIndex();
            mgmt.buildIndex('byNameMixed', Vertex.class).addKey(name, Mapping.TEXT.asParameter()).buildMixedIndex("search");
            mgmt.buildIndex('byTypeMixed', Vertex.class).addKey(type, Mapping.TEXT.asParameter()).buildMixedIndex("search");
            mgmt.buildIndex('byGeoMixed', Vertex.class).addKey(location).buildMixedIndex("search");
        }
        mgmt.commit();
    }

    public void run() {
        while (true) {
            try {
                StompFrame frame = connection.receive();
                onMessage(frame);
                //acking is done inside the above method
            } catch (SocketTimeoutException e) {
                //timeouts are not fatal (but this will happen a lot, so let's not log it)
                //logging.warn("Timeout on connection to Apollo.  Trying again (infinitely)...");
            }
        }
    }
}

neuron = new Neuron();
neuron.initialize();
neuron.initializeIndexing();
neuron.run();
