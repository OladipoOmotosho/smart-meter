# Independent fingerprint vectors

These literal bytes follow design §4. The two hexadecimal values were calculated
with macOS `shasum -a 256` on the literal ASCII strings, before running the
fingerprint implementation. No newline was included:

```sh
printf %s '["smart-meter/reading/v1","AMPDS2-WHE","2012-04-01T00:00:00Z",5200,"Wh",0]' | shasum -a 256
printf %s '["smart-meter/key/v1","AMPDS2-WHE","2012-04-01T00:00:00Z"]' | shasum -a 256
```

The reading digest covers all five fields. The record key covers only meter
and interval. The domain strings make the two byte formats distinct and
identify version 1. Changing the wire format requires a new version and
run/registry; it cannot reinterpret existing commitments.
