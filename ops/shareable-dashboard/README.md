# PEREZ-AI Secure Shareable Command Center

This layer puts the existing dashboard behind Nginx Basic Authentication and HTTPS while keeping the Python dashboard private on `127.0.0.1:8787`.

## Architecture

`Phone / PC -> HTTPS :443 -> Nginx auth -> 127.0.0.1:8787 -> existing PEREZ-AI dashboard`

The trading engine is not exposed directly. Dashboard actions continue to use the existing control plane and risk gates.

## Deploy

1. Create a DNS A record for your chosen hostname pointing to the EC2 public IP.
2. In the EC2 Security Group, allow TCP 80 and 443 from the internet. Do **not** expose TCP 8787.
3. From `~/PEREZ-AI-Trading-Bot`, run:

```bash
sudo DOMAIN=dashboard.example.com ADMIN_USER=perez bash ops/shareable-dashboard/setup.sh
```

The script prompts for the password without putting it in shell history. It installs Nginx, Certbot and the certificate plugin, configures the reverse proxy, enables HTTPS redirect, and verifies that the dashboard is still paper-only.

## Safety invariants

- `PAPER_MODE=true` is required.
- `ORDERS_ENABLED=false` is required.
- The Python dashboard must remain loopback-only.
- The public layer does not contain or modify broker credentials.
- Dashboard manual actions remain subject to the existing control/risk architecture.

For stronger production authentication, replace Basic Auth with an identity provider/MFA layer (for example AWS ALB authentication or a managed access proxy). AWS recommends encrypted HTTPS listeners and can integrate ALB with ACM certificates and identity-provider authentication. 
