# Make generation reproducible through immutable run revisions

Each Run Revision records a Generation Manifest binding the approved source, contracts, boilerplate, templates, model, renderer, drafts, evidence, and final artifact hashes. Repeating generation with unchanged inputs reuses accepted Section Drafts unless an explicit redraft is requested; changing the approved source creates a new revision and invalidates prior approval and drafts. Run evidence is retained internally until explicitly removed, and only the newest passing revision is client-facing.
