from .src.graph_pb2 import GraphDef
from .src.node_def_pb2 import NodeDef
from .src.versions_pb2 import VersionDef
from .src.attr_value_pb2 import AttrValue
from .src.tensor_shape_pb2 import TensorShapeProto

from distutils.version import LooseVersion


def replace(name, scope):
    return '/'.join([scope[name], name])


def parse(graph):
    import torch
    scope = {}
    for n in graph.nodes():
        inputs = [i.uniqueName() for i in n.inputs()]
        for i in range(1, len(inputs)):
            scope[inputs[i]] = n.scopeName()

        uname = next(iter(n.outputs())).uniqueName()
        assert n.scopeName() != '', '{} has empty scope name'.format(n)
        scope[uname] = n.scopeName()
    if LooseVersion(torch.__version__) >= LooseVersion("0.4"):
        scope['0'] = 'input'
    else:
        scope['1'] = 'input'

    nodes = []
    for n in graph.nodes():
        attrs = {k: n[k] for k in n.attributeNames()}
        attrs = str(attrs).replace("'", ' ')  # singlequote will be escaped by tensorboard
        if any(i.uniqueName() not in scope.keys() for i in n.inputs()):  # 0.3.1 workaround
            continue
        inputs = [replace(i.uniqueName(), scope) for i in n.inputs()]
        outputnode = next(iter(n.outputs()))  # FIXME: only first output is considered
        uname = outputnode.uniqueName()
        if outputnode.type().kind() == 'TensorType':
            outputsize = outputnode.type().sizes()
            nodes.append({'name': replace(uname, scope),
                          'op': n.kind(),
                          'inputs': inputs,
                          'attr': attrs,
                          'outputsize': outputsize})
        else:
            nodes.append({'name': replace(uname, scope), 'op': n.kind(), 'inputs': inputs, 'attr': attrs})

    for n in graph.inputs():
        uname = n.uniqueName()
        if uname not in scope.keys():
            scope[uname] = 'unused'
        outputsize = n.type().sizes()
        nodes.append({'name': replace(uname, scope),
                      'op': 'Parameter',
                      'inputs': [],
                      'attr': str(n.type()),
                      'outputsize': outputsize})

    return nodes


def graph(model, args, verbose=False):
    import torch
    with torch.onnx.set_training(model, False):
        try:
            trace, _ = torch.jit.get_trace_graph(model, args)
        except RuntimeError:
            print("Error occurs, checking if it's onnx problem...")
            try:
                torch.onnx.export(model, args, "/tmp/dummy.pb", verbose=True)
            except RuntimeError:
                print("Your model fails onnx too, please report to onnx team")
            print('No graph saved')
            return GraphDef(versions=VersionDef(producer=22))
    if LooseVersion(torch.__version__) >= LooseVersion("0.4"):
        torch.onnx._optimize_trace(trace, False)
    else:
        torch.onnx._optimize_trace(trace)
    graph = trace.graph()
    if verbose:
        print(graph)
    list_of_nodes = parse(graph)
    nodes = []
    for node in list_of_nodes:
        if 'outputsize' in node.keys():
            shapeproto = TensorShapeProto(
                dim=[TensorShapeProto.Dim(size=d) for d in node['outputsize']])
            nodes.append(
                NodeDef(name=node['name'], op=node['op'], input=node['inputs'],
                        attr={'lanpa': AttrValue(s=node['attr'].encode(encoding='utf_8')),
                        '_output_shapes': AttrValue(list=AttrValue.ListValue(shape=[shapeproto]))}))
        else:
            nodes.append(
                NodeDef(name=node['name'], op=node['op'], input=node['inputs'],
                        attr={'lanpa': AttrValue(s=node['attr'].encode(encoding='utf_8'))}))
    return GraphDef(node=nodes, versions=VersionDef(producer=22))
