"""Local backend for Final Round Recovered.

The recovered Electron app keeps its original pages, IPC and realtime client.
Everything the vendor's servers used to do runs in this package instead, as a
separate process that the Electron main process starts and talks to over
loopback HTTP and WebSocket:

* ``accounts``      local sign-in (administrator activation, members, sessions)
* ``workspace``     goals, library documents, playbooks, sessions and history
* ``documents``     text extraction for resumes and materials
* ``retrieval``     choosing the parts of large materials that matter right now
* ``openai``        the only module that talks to OpenAI (HTTP, SSE, WebSocket)
* ``realtime``      the live interview engine: transcription, speaker lanes,
                    interviewer translation, question extraction and streamed
                    bilingual answer hints
* ``screen``        screenshot analysis during a session
* ``app``           the aiohttp application that wires the pieces together

Data formats on disk are the same ones the earlier JavaScript backend wrote, so
existing accounts and workspaces keep working.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
