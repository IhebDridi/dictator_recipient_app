#!/bin/bash
otree resetdb
export DATABASE_URL=${POSTGRESQL_ADDON_URI}
otree prodserver 9000
