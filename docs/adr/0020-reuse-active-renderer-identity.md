# Reuse the active installation's office renderer identity

The `__05` study run constructed all three documents but Render Assurance found no office renderer, even though the active release had passed its LibreOffice installation smoke. The rootless LibreOffice launcher was available to the smoke command through its `PATH`; the study operation did not have a stable discovery path to that launcher.

Renderer discovery now checks the executable recorded by the active installation smoke before searching the current process environment. It accepts that record only when the installation and active smoke passed, the recorded active root matches the current skill root, and the absolute executable still passes the normal version probe. A stale or unavailable record falls back to host discovery. This keeps renderer identity tied to the active installation without adding a host-specific path or dependency to the packaged skill.

The offline regression test simulates a smoke environment with LibreOffice on `PATH` and a study environment without it. It verifies that the study still discovers the same executable and rejects a record for another installation root.

The later `__06` preflight showed the unsigned manual-review route has no promoted installation record by design. For that route, renderer discovery also checks `clinical-office-runtime/bin` under the same Hermes profile that owns `skills/clinical-document-generation`. It accepts only an executable whose resolved path remains within that profile, and still probes its version. This leaves the worker's restricted `PATH` and the promoted-runtime integrity guard intact. An unsigned smoke record must not be used as a substitute for promotion evidence.
