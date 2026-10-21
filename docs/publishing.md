# Publishing to PyPI

The `Publish to PyPI` workflow builds a source distribution and wheel when a
`v*` tag is pushed, then publishes them using GitHub Actions OIDC trusted
publishing. No PyPI API token is needed.

Before the first release, configure:

1. A GitHub environment named `pypi` in `paulgessinger/histcmp`. Restrict its
   deployment tags to `v*`.
2. A trusted publisher for the `histcmp` project on PyPI with these values:
   - Owner: `paulgessinger`
   - Repository: `histcmp`
   - Workflow filename: `publish.yml`
   - Environment: `pypi`

To release, update `project.version` in `pyproject.toml`, refresh `uv.lock` with
`uv lock`, and commit the changes. Tag that commit with the matching version
(for example, `v0.10.1`) and push the tag. Choose a version that has not already
been uploaded to PyPI; the workflow does not skip existing distributions.

The build and publish jobs are separate. Only the publish job has permission
to request an OIDC token, and it uploads the artifacts produced by the build
job without checking out or executing project code.
