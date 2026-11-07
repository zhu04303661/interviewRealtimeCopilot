"""Per-account workspace: storage, records, document preparation and the HTTP API.

Layout on disk (shared with the earlier JavaScript backend)::

    <workspace_dir>/<username>/workspace.json   all metadata for one account
    <workspace_dir>/<username>/files/<id>       uploaded originals and recordings
    <workspace_dir>/<username>/files/<id>.txt   text prepared from a document
"""
