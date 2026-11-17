# Remote SSH over Tailscale

Run `sudo scripts/install-tailscale.sh` over the local Ethernet connection, then enroll the Pi under the owner's personal Tailscale account:

```sh
sudo tailscale up --hostname=kisero-boat --accept-dns=false --accept-routes=false --ssh
```

Use the sign-in link from the command to select the personal tailnet. In the Tailscale app on the Mac, add or switch to the same account. The default personal tailnet SSH policy permits an owner to connect to their own device as a non-root user. With a customized policy, grant the owner's identity TCP port 22 and Tailscale SSH as `admin` on the boat Pi.

Check the Pi's address with `tailscale ip -4`. On the Mac, verify `tailscale ping kisero-boat` and connect using `tailscale ssh admin@kisero-boat`. Using the Tailscale IP instead of the name also works when MagicDNS is unavailable. A connection through a Tailscale relay is sufficient for SSH.

The boat Pi uses its existing uplink route and the dongle can stay behind carrier NAT. Avoid advertising the boat Wi-Fi subnet or configuring the Pi as an exit node. Verify remote SSH again with the Pi's Ethernet disconnected before depending on the boat's 4G connection.

If you need local recovery, reconnect the Ethernet cable and use the Pi's LAN IP with its existing OpenSSH service. Never store sign-in links, auth keys, or node state in Git.
