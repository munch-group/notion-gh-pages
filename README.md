
![](https://github.com/munch-group/munch-group-template/actions/workflows/quarto-publish.yml/badge.svg?event=push)

# Template repository for a library project

## Initial set up

- In the link above, replace `libraryname` with your library's name.
- Rename the `libraryname` folder to the name of your library, do *not* use hyphens, '-', in the name. 
- Replace all instances of `libraryname`, `modulename`, and `functionname` for the names of/in your library (`Shift-Cmd-F` in VScode). 

![example event parameter](https://github.com/munch-group/libraryname/actions/workflows/quarto-publish.yml/badge.svg?event=push)

## Development

In addition to any dependencies of your library, the development setup requires [quarto](https://quarto.org) the following packages:

conda-forge::jupyter
conda-forge::nbconvert
conda-forge::quartodoc 
conda-forge::gh
conda-forge::git
conda-forge::pip

## Version

The only version you need to change is the one in `setup.cfg`.

## Unit tests

Test are put in `test/test_modulename.py`. Run these and all other `test_*` files you create by running `./scripts/test.sh`.

## Creating docs

Use type hits (with the `typing` module) for code and add this to your `settings.json` in VScode.

```
"files.associations": {
    "*.qmd": "quarto"
},
"autoDocstring.docstringFormat": "numpy",
"autoDocstring.startOnNewLine": true,
"autoDocstring.customTemplatePath": "docs/autodoc.mustache",
```

That lets you can autogenerate doc-strings by typing `"""` at the top of your functions.

## Publishing docs

Docs are published to your github pages site `https://{user}.github.io/{libraryname}`. The template is set up for the user `munch-group`, but you can substitute all its instances for your own github user name.

Run all documentation notebooks inplace by running `./docs-run-notebooks.sh`. Build and render all documentation by running `./docs-build-render.sh`.

## Publishing conda package

Once pushed to github the library can be published as a conda package by running `./conda-release.sh`.

Publishing the conda package to anaconda requires that you set up a github secret, `ANACONDA_TOKEN`, that you create on your anaconda.org account.

## Library dependencies

Dependencies are managed in `pyproject.toml` and automatically read by `conda-build/meta.yaml`.

## Entry points

Entry points are defined in `pyproject.toml` and automatically read by `conda-build/meta.yaml`.