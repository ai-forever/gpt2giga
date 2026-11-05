# Russian Trusted Root CA

Public trust anchor distributed for GigaChat TLS verification. No private key is included.

- Downloaded on 2026-11-05 from https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.cer over verified HTTPS.
- Official guidance: https://developers.sber.ru/docs/ru/gigachat/certificates
- Subject/issuer: C=RU, O=The Ministry of Digital Development and Communications, CN=Russian Trusted Root CA.
- Validity: 2022-03-01 through 2032-02-27.
- SHA-256 certificate fingerprint: `D2:6D:2D:02:31:B7:C3:9F:92:CC:73:85:12:BA:54:10:35:19:E4:40:5D:68:B5:BD:70:3E:97:88:CA:8E:CF:31`.

The gateway loads this into its GigaChat client context alongside the usual CA
bundle. It never modifies the OS or certifi store and never downloads certificates
at runtime. Explicit CA bundles/SSL contexts take precedence. To update, download
from the official source over verified TLS, inspect the CA identity and validity,
verify its self-signature, and update the file and fingerprint together.
