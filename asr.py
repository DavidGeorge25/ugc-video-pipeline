import sys, json, subprocess, numpy as np, sherpa_onnx
import os
M=os.path.join(os.path.dirname(os.path.abspath(__file__)),"models","sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8")+"/"
def transcribe(path):
    pcm=subprocess.run(["ffmpeg","-v","error","-i",path,"-ac","1","-ar","16000","-f","s16le","-"],capture_output=True).stdout
    a=np.frombuffer(pcm,np.int16).astype(np.float32)/32768
    rec=sherpa_onnx.OfflineRecognizer.from_transducer(encoder=M+"encoder.int8.onnx",decoder=M+"decoder.int8.onnx",joiner=M+"joiner.int8.onnx",tokens=M+"tokens.txt",model_type="nemo_transducer",num_threads=2)
    words=[]; CH=20*16000; off=0
    # chunk on quiet points ~20s
    env=np.convolve(np.abs(a),np.ones(1600)/1600,'same')
    while off<len(a):
        end=min(len(a),off+CH)
        if end<len(a):
            w=env[end-5*16000:end]; end=end-5*16000+int(np.argmin(w))
        s=rec.create_stream(); s.accept_waveform(16000,a[off:end]); rec.decode_stream(s); r=s.result
        toks,ts=r.tokens,r.timestamps
        cur=None
        for t,tt in zip(toks,ts):
            T=off/16000+tt
            if t.startswith(" ") or cur is None:
                if cur: words.append(cur)
                cur={"w":t.strip(),"s":T,"e":T+0.08}
            else: cur["w"]+=t; cur["e"]=T+0.08
        if cur: words.append(cur)
        off=end
    # end times: next word start capped
    for i,w in enumerate(words):
        nxt=words[i+1]["s"] if i+1<len(words) else w["e"]+0.4
        w["e"]=min(nxt, w["s"]+max(0.25,0.09*len(w["w"])))
    return words
if __name__=="__main__":
    w=transcribe(sys.argv[1]); json.dump(w,open(sys.argv[2],"w"),indent=0)
    print(" ".join(f"{x['w']}" for x in w))
