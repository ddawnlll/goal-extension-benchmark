import json,subprocess,os
tools=[{"type":"function","function":{"name":f"tool_{i}","description":"A coding tool. "*20,"parameters":{"type":"object","properties":{"p":{"type":"string"},"n":{"type":"number"}},"required":["p"]}}} for i in range(29)]
big="You are a coding agent for Pi-Bolt. "*600
body=json.dumps({"model":"deepseek-v4.1-flash","stream":True,"max_tokens":2500,"tools":tools,"reasoning_effort":"high",
 "messages":[{"role":"system","content":big},{"role":"user","content":"Think carefully about the repository, then call tool_5 with p=/tmp/report.py."}]})
print("bytes",len(body),flush=True)
for i in range(20):
    p=subprocess.run(["curl","-sN","-o","/dev/null","-w","%{http_code} %{time_total} %{size_download}","-m","300","-H","Content-Type: application/json","-X","POST",os.environ["URL"],"--data-binary",body],capture_output=True,text=True)
    print(i,p.stdout.strip(),p.returncode,flush=True)
