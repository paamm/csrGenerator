#!/bin/sh

# Create folders for db and jobs
mkdir -p "$CSR_JOBS"
mkdir -p "$CSR_DB"

exec "$@"