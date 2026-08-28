# Security Notes

## ⚠️ CRITICAL: API Key Management

### Never Commit API Keys
- The `.env` file contains sensitive API keys and is **gitignored by default**
- **NEVER** commit `.env` to version control
- **NEVER** share your `.env` file or API keys publicly

### If You Accidentally Expose Keys
If you accidentally commit `.env` with real keys:

1. **IMMEDIATELY revoke the exposed keys**:
   - Groq: https://console.groq.com/keys
   - Gemini: https://aistudio.google.com/app/apikey
   - OpenAI: https://platform.openai.com/api-keys

2. **Generate new keys** from the same consoles

3. **Remove `.env` from git history**:
   ```bash
   git rm --cached .env
   git commit -m "Remove sensitive keys"
   git push --force  # Only if already pushed
   ```

4. **Update your local `.env`** with the new keys

## File Upload Limits

The Streamlit UI has safety limits to prevent resource exhaustion:

- **Max file size**: 10 MB per file
- **Max total rows**: 10,000 combined rows (website + gateway)

For larger datasets, use the CLI: `python main.py --website large.csv --gateway large.csv`

## Known Security Considerations

### 1. PII Redaction
- Phone numbers matching `\d{10}` pattern are automatically redacted
- Only 4 columns are sent to LLM: `order_id`, `amount`, `date`, `reference`
- Customer names, emails, and extra columns are never sent to the API

### 2. Prompt Injection Defense
- Input sanitization removes non-ASCII characters
- Text length limited to 100 characters per field
- Quotes are escaped to prevent prompt breaking

**Known limitation**: Semantic prompt injection (e.g., "ignore previous instructions") is only partially mitigated. For production use, implement additional filtering.

### 3. Rate Limiting
- Soft cap: `LLM_MAX_CALLS_PER_RUN = 50` (configurable via environment variable)
- Cost estimation shown before LLM execution
- No hard financial cap implemented (manual oversight required)

### 4. Temp File Cleanup
- Uploaded files are cleaned up on app exit via `atexit` handler
- Manual cleanup: temp files are stored in system temp directory with `.csv` suffix

## Production Deployment Checklist

**This app is designed for local demo use.** For production deployment, implement:

- [ ] Authentication/authorization (OAuth2, JWT)
- [ ] CSRF protection
- [ ] Rate limiting per user/IP
- [ ] Database instead of in-memory processing
- [ ] Input validation against malicious CSV content
- [ ] Audit logging to secure storage (not just local JSONL)
- [ ] API key rotation policy
- [ ] Monitoring and alerting
- [ ] HTTPS/TLS enforcement
- [ ] Content Security Policy (CSP) headers

## Reporting Security Issues

If you discover a security vulnerability, please:
1. **Do NOT** open a public issue
2. Contact the maintainer directly
3. Provide detailed reproduction steps
4. Allow reasonable time for a fix before disclosure

## Compliance Notes

### Data Privacy
- This tool processes financial transaction data
- Ensure compliance with local data protection regulations (GDPR, CCPA, etc.)
- LLM providers (OpenAI, Gemini, Groq) may process data on their servers
- Review each provider's data processing agreement before production use

### PCI DSS
- This tool does NOT handle credit card numbers or cardholder data
- If processing card transactions, ensure PCI DSS compliance separately

## License
This software is provided "AS IS" without warranty. Use at your own risk.
