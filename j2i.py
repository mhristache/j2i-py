#! /usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import os
import yaml
import jinja2
from collections import OrderedDict
from zipfile import ZipFile
from StringIO import StringIO
import shutil
import sys
import uuid
import netaddr


JINJA2_FILE_EXTENSIONS = ['.j2', '.jinja2']


def main(input_args):
    parser = argparse.ArgumentParser(description='Jinja2 CLI - Improved')
    parser.add_argument('-i',
                        dest="input_file",
                        help='the input file in yaml format',
                        required=True)

    parser.add_argument('-t',
                        dest="templates_dir",
                        required=True,
                        help='the directory where to look for '
                             'jinja2 template files')

    parser.add_argument('-o',
                        dest="output_file",
                        default="j2i_output.zip",
                        help='the name/path to the output zip file.'
                             'Default: j2i_output.zip')

    parser.add_argument('--version', action='version', version='0.1')

    args = parser.parse_args(input_args)

    try:
        content = gen_content(args.input_file, args.templates_dir)
    except BaseException:
        raise
    else:
        # force .zip extension on the output file
        output_file_path = args.output_file
        _, ext = os.path.splitext(output_file_path)
        if ext != '.zip':
            output_file_path += '.zip'
        with open(output_file_path, 'w') as out_file:
            shutil.copyfileobj(content, out_file)

        print("Done! Output saved to: {0}".format(output_file_path))


def gen_content(input_file_path, templates_dir_path):
    # parse the templates dirs and extract the templates keys
    templates = get_all_templates(templates_dir_path)
    assert templates, "No templates found in {}".format(templates_dir_path)

    # get the files are supposed to be ignored (not rendered with jinja2)
    to_ignore = get_files_to_be_ignored(templates_dir_path)

    # create a custom tag constructor for each template key
    for key in templates.keys():
        yaml.add_constructor(u'!{}'.format(key), obj_constructor)

    # open and parse the input yaml
    with open(input_file_path) as f:
        params = yaml.load(f)

    # find the configured key name for all the Obj defined
    # Note: the objects are expected to be defined at the top level only
    # TODO: maybe add support for nested objects
    objs = {k: v for k, v in params.items() if issubclass(v.__class__, Obj)}

    # inject the object names and kind into the objects before the objects
    # are used in the rendering so that the updated object is used via anchors
    for name, obj in objs.items():
        kind = obj.__class__.__name__
        # add the name and kind as attributes to the obj
        add_attr_to_obj(obj, 'keyname', name)
        add_attr_to_obj(obj, 'kind', kind)

    # render the templates for each defined object
    content_store = {}
    for name, obj in objs.items():
        kind = obj.__class__.__name__
        for template in templates[kind]:
            # render the file if it's not supposed to be ignored
            should_ignore = reduce(
                lambda a, b: a or b,
                [template.startswith(x) for x in to_ignore],
                False)
            if should_ignore:
                res = (template, file)
            else:
                res = parse_template(template, obj=obj, params=params)
                if res:
                    res = (res, str)
            if res:
                file_path = gen_output_file_path(kind,
                                                 name,
                                                 template,
                                                 templates_dir_path)
                content_store[file_path] = res
    assert content_store, "No content could be generated"
    return create_zip(content_store)


def get_files_to_be_ignored(dir_):
    """Check dir_ for a .j2i_ignore file and ignore the files inside"""
    res = []
    ignore_file = os.path.join(dir_, '.j2i_ignore')
    try:
        with open(ignore_file) as f:
            for l in f.readlines():
                p = os.path.join(dir_, l.strip())
                res.append(p)
    except IOError:
        pass
    return res


def add_attr_to_obj(obj, attr, value):
    """Creates a new attribute in the object with the given value
    If the object already has that attribute configure,
    it will try to use <attr>_, <attr>__ etc"""
    if not hasattr(obj, attr):
        setattr(obj, attr, value)
    else:
        new_attr = attr + '_'
        add_attr_to_obj(obj, new_attr, value)


def get_all_templates(root_dir):
    """Templates files are expected in subdirectories inside root_dir. The name
    of each first level subdir is used as template type.

    E.g. for assuming the root_dir is the 'templates' dir in the example below:

    templates
    ├── bar
    │   ├── bar_template1.j2
    │   ├── bar_template2.txt.jinja2
    │   └── subbar
    │       └── subbar_template.j2
    └── foo
        ├── template1.txt.j2
        └── template2

    The function will return:

    {'bar': ['abspath/to/bar/bar_template1.j2',
             'abspath/to/bar/bar_template2.txt.jinja2',
             'abspath/to/bar/subbar/subbar_template.j2]
    'foo': ['abspath/to/foo/template1.txt.j2',
            'abspath/to/foo/template2']
    }

    :param root_dir: the directory where to start looking
    :type root_dir: str
    :rtype: dict[str, list[str]]
    """
    res = {}
    keys = None

    for path, subdirs, files in os.walk(root_dir):
        if keys is None:
            keys = subdirs
        for name in files:
            # find which key (parent subdir) the file belongs to
            for key in keys:
                key_path = os.path.join(root_dir, key)
                if path.startswith(key_path):
                    file_path = os.path.join(path, name)
                    res.setdefault(key, []).append(file_path)
    return res


def parse_template(template, **kwargs):
    """Parse the given template with Jinja2 engine
    using the given kwargs as input"""
    template_dir = os.path.dirname(template)
    template_file_name = os.path.basename(template)
    j2_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_dir),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        extensions=['jinja2.ext.loopcontrols', 'jinja2.ext.do'],
        undefined=jinja2.StrictUndefined,
    )

    # add some useful custom filters
    j2_env.filters['uuid'] = j2_uuid
    j2_env.filters['debug'] = j2_debug
    j2_env.filters['raise'] = j2_raise
    j2_env.filters['iprange'] = j2_ip_range
    j2_env.filters['ipnetwork'] = j2_ip_network
    j2_env.filters['ipaddress'] = j2_ip_address

    template = j2_env.get_template(template_file_name)
    res = template.render(**kwargs)
    return res


def j2_uuid(s):
    """"Jinja2 custom filter that transforms the given string into a UUID
    """
    return uuid.uuid5(uuid.NAMESPACE_DNS, s)


def j2_debug(s):
    """Jinja2 custom filter that prints the given string to stdout
    """
    print(s)
    return ''


def j2_raise(s):
    """Jinja2 custom filter that raises an error
    """
    raise Exception(s)


def j2_ip_range(s):
    """Jinja2 custom filter that transforms an IP range string,
    e.g. 192.168.0.1-192.168.0.4, into a netaddr.IPRange()"""
    start, _, end = s.partition("-")
    return netaddr.IPRange(start, end)


def j2_ip_network(s):
    """Jinja2 custom filter that converts a subnet in string format to
    netaddr.IPNetwork
    """
    return netaddr.IPNetwork(s)


def j2_ip_address(s):
    """Jinja2 custom filter that converts an IP in string format to
    netaddr.IPAddress
    """
    return netaddr.IPAddress(s)


class Obj(object):
    pass


def obj_constructor(loader, node):
    values = OrderedDict(loader.construct_mapping(node, deep=True))
    kind = str(node.tag.lstrip("!"))
    cls = type(kind, (Obj, ), values)
    return cls()


def gen_output_file_path(obj_kind, obj_name, template, root_dir):
    """Generate the path to be used to save the rendered template file"""
    # keep the directory structure from the templates dir,
    # relative to the template key
    common_path = os.path.join(root_dir, obj_kind)
    rel_path = os.path.relpath(template, common_path)

    file_path = os.path.join(obj_name, rel_path)

    # create the file name to be used in the output
    # remove the jinja2 related extensions if present
    file_path_no_ext, file_ext = os.path.splitext(file_path)
    if file_ext in JINJA2_FILE_EXTENSIONS:
        file_path = file_path_no_ext

    return file_path


def create_zip(content_store):
    """Create a zip file with the given content"""

    # create an in memory file to store the zipped hot package
    in_mem_file = StringIO()

    # create the a zip file to store the content
    zip_file = ZipFile(in_mem_file, 'w')

    for file_name, content in content_store.items():
        if content[1] == file:
            zip_file.write(content[0], file_name)
        elif content[1] == str:
            zip_file.writestr(file_name.encode('utf-8'),
                              content[0].encode('utf-8'))

    zip_file.close()
    in_mem_file.seek(0)

    return in_mem_file


if __name__ == "__main__":
    main(sys.argv[1:])
