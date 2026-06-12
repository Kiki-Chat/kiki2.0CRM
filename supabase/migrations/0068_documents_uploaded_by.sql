-- 0068: documents.uploaded_by_name (additive) — who put the file here. Filled by
-- the technician photo mirror ("Techniker: <Name>") so the project's Dokumente
-- tab shows which technician uploaded each Einsatzbericht photo (item 6 polish).
alter table documents
  add column if not exists uploaded_by_name text;
