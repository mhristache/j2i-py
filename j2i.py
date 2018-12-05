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


JINJA2_FILE_EXTENSIONS = ['.j2', '.jinja2']


def run(input_file_path, templates_dir_path):
    # parse the templates dirs and extract the templates keys
    templates = get_all_templates(templates_dir_path)

    # create a custom tag constructor for each template key
    for key in templates.keys():
        yaml.add_constructor(u'!{}'.format(key), obj_constructor)

    # open and parse the input yaml
    with open(input_file_path) as f:
        params = yaml.load(f)

    # find the configured key name for all the Obj defined
    # Note: the objects are expected to be defined at the top level only
    # TODO: maybe add support for nested objects
    objs = {k: v for k, v in params.items() if isinstance(v, Obj)}

    # the params which are not used for objects are considered global params
    global_params = {k: v for k, v in params.items() if k not in objs}

    # render the templates for each defined object
    content_store = {}
    for name, obj in objs.items():
        for template in templates[obj.kind]:
            res = parse_template(template, name=name,
                                 kind=obj.kind,
                                 obj=obj.params,
                                 globals=global_params)

            file_path = gen_output_file_path(obj.kind,
                                             name,
                                             template,
                                             templates_dir_path)
            content_store[file_path] = res

    return create_zip(content_store)


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
        extensions=['jinja2.ext.loopcontrols', 'jinja2.ext.do']
    )
    template = j2_env.get_template(template_file_name)
    res = template.render(**kwargs)
    return res


class Obj(object):

    def __init__(self, kind, params):
        self.kind = kind
        self.params = params

    def __repr__(self):
        return "Obj({})".format(self.kind)


def obj_constructor(loader, node):
    values = OrderedDict(loader.construct_mapping(node, deep=True))
    return Obj(node.tag.lstrip("!"), values)


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

    for file_, content_ in content_store.items():
        zip_file.writestr(file_.encode('utf-8'), content_.encode('utf-8'))

    zip_file.close()
    in_mem_file.seek(0)

    return in_mem_file


if __name__ == "__main__":
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

    args = parser.parse_args()

    templates_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), args.templates_dir))

    try:
        content = run(args.input_file, templates_dir)
    except BaseException as exp:
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
