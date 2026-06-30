#!/usr/bin/env python3
"""Minimal speedtest server. Browser -> instructions page. curl/wget -> bash
script. PowerShell -> ps1 script. Scripts measure real ISP download speed
against Cloudflare's public endpoint and print net speed only."""
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Cloudflare's public speed endpoint (what speed.cloudflare.com itself uses).
# Measures real internet speed, not loopback.
BYTES = 25_000_000
DOWN = f"https://speed.cloudflare.com/__down?bytes={BYTES}"

# __BASE__ is replaced with the request origin (avoids brace-escaping CSS/JS).
HTML = """<!doctype html><html lang=en><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>speedtest</title>
<style>
  /* green phosphor CRT */
  :root{--grn:#33ff66;--dim:#1f9a40;color-scheme:dark}
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:flex;padding:2rem 1rem;
    background:#000;color:var(--grn);
    font:15px/1.6 ui-monospace,"Courier New",monospace;
    text-shadow:0 0 4px rgba(51,255,102,.55)}
  /* margin:auto centers but stays scrollable when taller than viewport */
  /* scanline overlay */
  body::after{content:"";position:fixed;inset:0;pointer-events:none;z-index:9;
    background:repeating-linear-gradient(rgba(0,0,0,0) 0 2px,rgba(0,0,0,.28) 2px 3px)}
  .card{width:min(92vw,32rem);margin:auto;border:1px solid var(--grn);border-radius:4px;
    padding:1.5rem 1.75rem;box-shadow:0 0 18px rgba(51,255,102,.25),inset 0 0 40px rgba(51,255,102,.04)}
  h1{margin:0 0 1.25rem;font-size:1rem;font-weight:700;letter-spacing:.25em;text-transform:uppercase}
  h1::before{content:"\\2593 "}h1::after{content:" \\2593"}
  .stat{margin:.75rem 0}
  .stat .lbl{text-transform:uppercase;letter-spacing:.12em;font-size:.8rem;color:var(--dim)}
  .stat .val{font-size:1.9rem;font-weight:700}
  .stat .val::before{content:"> "}
  .stat .unit{font-size:.9rem;color:var(--dim)}
  /* blinking cursor */
  .stat .val.busy::after{content:"_";animation:blink 1s steps(1) infinite}
  @keyframes blink{50%{opacity:0}}
  button{margin-top:1.25rem;width:100%;padding:.7rem;cursor:pointer;
    font:inherit;letter-spacing:.15em;text-transform:uppercase;
    color:var(--grn);background:transparent;border:1px solid var(--grn);border-radius:3px;
    text-shadow:inherit;transition:.12s}
  button:hover:not(:disabled){background:var(--grn);color:#000;text-shadow:none}
  button:disabled{opacity:.4;cursor:default}
  button::before{content:"[ "}button::after{content:" ]"}
  .cmds{margin-top:1.5rem;font-size:.85rem;color:var(--dim);
    border-top:1px dashed var(--dim);padding-top:1rem}
  .cmds p{margin:.6rem 0 .25rem}
  .row{display:flex;align-items:center;gap:.5rem}
  pre{margin:0;color:var(--grn);overflow:auto;font-size:.85rem;flex:1}
  pre::before{content:"$ "}
  .cp{flex:none;cursor:pointer;background:transparent;color:var(--dim);
    border:1px solid var(--dim);border-radius:3px;padding:.15rem .4rem;
    font:inherit;font-size:.8rem;text-shadow:inherit}
  .cp:hover{color:var(--grn);border-color:var(--grn)}
</style>
<body>
<div class=card>
  <h1>speedtest</h1>
  <div class=stat><div class=lbl>download</div>
    <div class=val id=down>--<span class=unit> Mbps</span></div></div>
  <div class=stat><div class=lbl>upload</div>
    <div class=val id=up>--<span class=unit> Mbps</span></div></div>
  <button id=go>run test</button>
  <div class=cmds>
    <p>macOS / Linux</p>
    <div class=row><button class=cp data-t=c1 title=copy>⧉</button><pre id=c1>curl -s __BASE__/ | sh</pre></div>
    <p>Windows (PowerShell)</p>
    <div class=row><button class=cp data-t=c2 title=copy>⧉</button><pre id=c2>iwr __BASE__/ | iex</pre></div>
  </div>
</div>
<script>
const CF="https://speed.cloudflare.com";
const fmt=n=>n.toFixed(n<10?2:n<100?1:0);
async function down(){
  const t=performance.now();
  const r=await fetch(CF+"/__down?bytes=50000000",{cache:"no-store"});
  if(!r.ok) throw new Error("down HTTP "+r.status);
  const b=await r.arrayBuffer();
  return b.byteLength*8/((performance.now()-t)/1000)/1e6;
}
async function up(){
  const body=new Uint8Array(15000000);
  const t=performance.now();
  const r=await fetch(CF+"/__up",{method:"POST",body,cache:"no-store"});
  if(!r.ok) throw new Error("up HTTP "+r.status);
  return body.length*8/((performance.now()-t)/1000)/1e6;
}
const go=document.getElementById("go");
go.onclick=async()=>{
  go.disabled=true;go.textContent="testing";
  const d=document.getElementById("down"),u=document.getElementById("up");
  const set=(el,html)=>el.innerHTML=html;
  d.classList.add("busy");u.classList.add("busy");
  set(d,"");set(u,"");
  try{
    set(d,fmt(await down())+'<span class=unit> Mbps</span>');d.classList.remove("busy");
    set(u,fmt(await up())+'<span class=unit> Mbps</span>');u.classList.remove("busy");
  }catch(e){
    d.classList.remove("busy");u.classList.remove("busy");
    set(d,'<span class=unit>'+e.message+'</span>');set(u,'<span class=unit>'+e.message+'</span>');
  }
  go.disabled=false;go.textContent="run again";
};
go.click();
document.querySelectorAll(".cp").forEach(b=>b.onclick=async()=>{
  await navigator.clipboard.writeText(document.getElementById(b.dataset.t).textContent);
  b.textContent="✓";setTimeout(()=>b.textContent="⧉",1200);
});
</script>
"""

# N parallel downloads saturate the link. Sum ACTUAL bytes (not requested) /
# wall-clock, so a throttled/short transfer reports an honest low number.
BASH = """#!/bin/sh
n=10 secs=8
down="https://speed.cloudflare.com/__down?bytes=1000000000"
up="https://speed.cloudflare.com/__up"
# ponytail: parallel append of tiny <12B lines; atomic enough on linux/macos.

# --- download: each curl runs up to $secs then aborts; sum actual bytes ---
td=$(mktemp); t0=$(date +%s.%N)
for i in $(seq $n); do curl -s --max-time $secs -o /dev/null -w '%{{size_download}}\\n' "$down" >> "$td" & done
wait
t1=$(date +%s.%N)
bd=$(awk '{{s+=$1}} END{{print s}}' "$td"); rm -f "$td"
if [ "$bd" -lt 1000000 ]; then echo "Rate limited"; exit 1; fi
awk "BEGIN{{printf \\"Download: %.2f Mbps\\\\n\\", $bd*8/($t1-$t0)/1000000}}"

# --- upload: POST a 100MB payload, abort at $secs, sum actual bytes sent ---
pay=$(mktemp); head -c 100000000 /dev/zero > "$pay"
tu=$(mktemp); u0=$(date +%s.%N)
for i in $(seq $n); do curl -s --max-time $secs -o /dev/null -w '%{{size_upload}}\\n' --data-binary @"$pay" "$up" >> "$tu" & done
wait
u1=$(date +%s.%N)
bu=$(awk '{{s+=$1}} END{{print s}}' "$tu"); rm -f "$tu" "$pay"
awk "BEGIN{{printf \\"Upload:   %.2f Mbps\\\\n\\", $bu*8/($u1-$u0)/1000000}}"
"""

PS1 = """$sw=[Diagnostics.Stopwatch]::StartNew()
$n=(New-Object Net.WebClient).DownloadData('{down}').Length
$sw.Stop()
"Download: {{0:N2}} Mbps" -f ($n*8/$sw.Elapsed.TotalSeconds/1000000)
"""


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        # honor proxy scheme (Render/CF terminate TLS upstream).
        scheme = self.headers.get("X-Forwarded-Proto", "http")
        base = f"{scheme}://{self.headers.get('Host', 'localhost')}"
        ua = self.headers.get("User-Agent", "").lower()
        # powershell iwr UA also contains "mozilla", so check it first.
        if "powershell" in ua:
            body, ctype = PS1.format(down=DOWN), "text/plain"
        elif "mozilla" in ua:
            body, ctype = HTML.replace("__BASE__", base), "text/html"
        else:  # curl, wget, anything else
            body, ctype = BASH.format(down=DOWN), "text/plain"
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    # Render sets $PORT; allow argv override for local use.
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", 8000))
    print(f"serving on 0.0.0.0:{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
