# PEREZ-AI Secure Shareable Command Center

This layer puts the existing dashboard behind Nginx Basic Authentication and HTTPS while keeping the Python dashboard private on `127.0.0.1:8787`.

## Architecture

`Phone / PC -> HTTPS :443 -> Nginx auth -> 127.0.0.1:8787 -> existing PEREZ-AI dashboard`

The trading engine is not exposed directly. Dashboard actions continue to use the existing control plane and risk gates.

## Deploy

### Fastest: no domain required

From `~/PEREZ-AI-Trading-Bot`:

```bash
sudo bash ops/shareable-dashboard/setup.sh
```

The script derives an HTTPS hostname from the EC2 public IPv4 using nip.io, prompts for the dashboard password without placing it in shell history, installs Nginx + Certbot, enables HTTPS, and verifies the paper-only safety state.

This hostname follows the EC2 public IP. For a permanent production URL, use an Elastic IP and/or supply your own DNS hostname.

### Custom domain

Point an A record at the EC2 public IP, then run:

```bash
sudo DOMAIN=dashboard.example.com ADMIN_USER=perez bash ops/shareable-dashboard/setup.sh
```

## Network requirement

In the EC2 Security Group, allow TCP 80 and 443 from the internet. Do **not** expose TCP 8787. The Python dashboard must remain loopback-only.

## Safety invariants

- `PAPER_MODE=true` is required.
- `ORDERS_ENABLED=false` is required.
- The Python dashboard must remain loopback-only.
- The public layer does not contain or modify broker credentials.
- Dashboard manual actions remain subject to the existing control/risk architecture.

For stronger production authentication, replace Basic Auth with an identity provider/MFA layer (for example AWS ALB authentication or a managed access proxy). AWS supports HTTPS listeners, ACM-managed certificates, and identity-provider authentication at the load-balancer layer. citeturn0search0turn0search6
