> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Import Code

> Bring local Python modules, files, and external repositories into your fal app's remote environment.

When your app spans multiple files, uses local utility modules, or depends on code from a private repository, you need a way to include that code in the remote environment where your [runners](/documentation/getting-started/runners-and-caching) execute. This page covers the mechanisms fal provides: `app_files` for local files and directories, `local_python_modules` for Python modules that should be serialized alongside your app, and `clone_repository` for pulling external Git repos at startup.

These mechanisms work with the [fal Runtime](/documentation/development/fal-runtime) (pip requirements). They are not available when using a [custom Docker container](/documentation/development/use-custom-container-image), where you should use `COPY` in your Dockerfile to include local files instead.

<Frame>
  <iframe className="w-full aspect-video rounded-lg" srcdoc="<style>*{padding:0;margin:0;overflow:hidden}html,body{height:100%}img,span{position:absolute;width:100%;top:0;bottom:0;margin:auto}span{height:1.5em;text-align:center;font:48px/1.5 sans-serif;color:white;text-shadow:0 0 0.5em black}</style><a href='https://www.youtube.com/embed/gDJJ9bppyV8?start=864&end=923&autoplay=1'><img src='/docs/images/video-thumbs/import-code.jpg' alt='App Files - fal Serverless'><span>▶</span></a>" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen />
</Frame>

<Warning>
  `app_files` and `local_python_modules` are only supported with the fal Runtime. If your app uses a custom `ContainerImage`, use `COPY` in your Dockerfile to include local files.
</Warning>

## Choosing the Right Mechanism

fal provides three ways to bring code into the remote environment, each suited to a different situation.

Use **`app_files`** when you have a multi-file project and want the remote environment to mirror your local directory structure. Files are uploaded and placed at the same relative paths, so imports and file reads work identically to local development. This is the recommended approach for most projects.

Use **`local_python_modules`** when you have a simple Python module that your app imports at the top level. The module is serialized (pickled) alongside your app class and made available on the remote Python path. This is lighter-weight than `app_files` but only works for importable Python packages.

Use **`clone_repository`** when you need to pull code from an external Git repository at runner startup. The clone happens inside `setup()`, so the code is available before your first request.

## App Files

The `app_files` attribute includes local files and directories in the remote environment, mirroring your local file layout exactly. Imports and file paths work the same way they do on your machine.

```python theme={null}
class MyApp(fal.App):
    app_files = [
        "utils/helper.py",
        "models",
        "checkpoint.pt",
    ]

    @fal.endpoint("/")
    def predict(self, input: MyInput) -> MyOutput:
        from utils.helper import process_data
        from models.classifier import MyModel

        result = process_data(input)
        model = MyModel.load_checkpoint("checkpoint.pt")
        return model.predict(result)
```

If your local project looks like this:

```
project/
├── my_fal_app.py
├── utils/
│   └── helper.py
└── models/
    └── classifier.py
```

Then on the runner, `from utils.helper import process_data` and `from models.classifier import MyModel` work exactly as they do locally. Files are placed relative to your app file location.

### Context Directory

By default, all file paths are resolved relative to the directory containing your fal app file. You can change this base directory with `app_files_context_dir`, which is useful for monorepos or when you need to include files from a parent directory:

```python theme={null}
class MyApp(fal.App):
    app_files_context_dir = "../"
    app_files = [
        "src/data_processing",
        "src/models",
        "weights",
        "utils",
    ]
```

All paths must be relative and within the context directory. Absolute paths and paths that escape the context directory (e.g., `../../outside`) are rejected. Included files are read-only on the runner.

### Ignoring Files

Use `app_files_ignore` to exclude files using regex patterns. fal excludes `.pyc`, `__pycache__/`, `.git/`, and `.DS_Store` by default.

```python theme={null}
class MyApp(fal.App):
    app_files = ["my_project/"]
    app_files_ignore = [
        r"\.pyc$",
        r"__pycache__/",
        r"\.git/",
        r"\.env$",
        r"test_.*\.py$",
    ]
```

Only include the files your app actually needs. Smaller deployments mean faster uploads and faster runner startup.

## Local Python Modules

The `local_python_modules` attribute ships a Python module alongside your app by serializing it into the deployment payload. This is a simpler mechanism than `app_files` - it adds the specified modules to the remote Python path so they can be imported directly. Use it when you have a small utility module that your app imports at the top level.

```python theme={null}
from mymodule import myfunction

class MyApp(fal.App):
    local_python_modules = ["mymodule"]

    @fal.endpoint("/")
    def predict(self, input: MyInput) -> MyOutput:
        myfunction(input)
        ...
```

For projects with multiple files, directories, or non-Python assets (configs, weights), `app_files` is the better choice because it preserves the full directory structure and supports ignore patterns.

## Git Repositories

Use `clone_repository` to pull code from a Git repository at runner startup. The clone happens inside `setup()`, so the repository is available before any requests are processed. Pin to a specific commit hash for reproducibility.

```python theme={null}
from fal.toolkit import clone_repository

class MyApp(fal.App):
    def setup(self):
        path = clone_repository(
            "https://github.com/myorg/myrepo",
            commit_hash="1418c53bcfaf4efc1034207dcb39d093d5fff645",
            include_to_path=True,
        )

        import myproject
        ...
```

Setting `include_to_path=True` adds the cloned directory to `PYTHONPATH`, so you can import modules from the repository directly. For private repositories, include a personal access token in the URL: `https://YOUR_TOKEN@github.com/myorg/private-repo.git`.
