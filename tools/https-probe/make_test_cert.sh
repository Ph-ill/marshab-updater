#!/bin/sh
# A throwaway ECDSA P-256 chain shaped like the real Let's Encrypt one (leaf + one
# intermediate, ~1.9 KB of PEM), for the probe only. Never committed (.gitignore).
# Real cert for ships: /home/box/.secrets/lv_tls/ (never in the repo, never printed).
set -e
cd "$(dirname "$0")"
mkdir -p testcert && cd testcert
NAME="${1:-voyage.coolphill.com}"
openssl ecparam -name prime256v1 -genkey -noout -out ca.key 2>/dev/null
openssl req -x509 -new -key ca.key -sha256 -days 3650 -subj "/CN=LV probe test CA" -out ca.pem
openssl ecparam -name prime256v1 -genkey -noout -out leaf.key 2>/dev/null
openssl req -new -key leaf.key -subj "/CN=$NAME" -out leaf.csr
printf "subjectAltName=DNS:%s,IP:192.168.4.1\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature\nextendedKeyUsage=serverAuth\n" "$NAME" > ext.cnf
openssl x509 -req -in leaf.csr -CA ca.pem -CAkey ca.key -CAcreateserial -days 90 -sha256 -extfile ext.cnf -out leaf.pem 2>/dev/null
cat leaf.pem ca.pem > fullchain.pem
# SEC1 "EC PRIVATE KEY" PEM, which mbedTLS parses; also DER copies (smaller, no base64 on the Pico).
openssl ec -in leaf.key -out privkey.pem 2>/dev/null
openssl x509 -in leaf.pem -outform DER -out leaf.der
openssl ec -in leaf.key -outform DER -out privkey.der 2>/dev/null
rm -f leaf.csr ext.cnf ca.srl
chmod 600 *.key privkey.*
echo "testcert/: fullchain.pem ($(wc -c < fullchain.pem) B), privkey.pem, ca.pem (trust this on a test phone/client), leaf.der, privkey.der"
