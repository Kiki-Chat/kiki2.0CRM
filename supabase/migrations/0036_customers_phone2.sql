-- Second phone number (e.g. Mobil) for customers. Additive, nullable — existing
-- rows keep phone2 = NULL; the manual edit form + CSV import (Mobil) write it.
alter table customers add column if not exists phone2 text;
