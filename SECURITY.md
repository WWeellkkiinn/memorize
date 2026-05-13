# Security Policy

## Reporting a Vulnerability

Please do not open a public issue for security vulnerabilities. Report them by emailing the maintainer directly (see GitHub profile).

## Known Limitations

- The web server uses HTTP Basic Auth. **Always deploy behind a TLS-terminating reverse proxy (e.g. Nginx, Caddy) when exposing to the internet.**
- Word audio is fetched from the Youdao dictionary API (`dict.youdao.com`). Each word you study is sent to Youdao's servers as part of the audio request.
