#!/bin/bash
# API to get JWT auth token for testing
curl --location 'http://10.199.207.78:8080/jwt-0.0.1-SNAPSHOT/auth/login' \
--header 'Content-Type: application/json' \
--data-raw '{
  "username": "shivaa@gmail.com",
  "password": "password123"
}'
