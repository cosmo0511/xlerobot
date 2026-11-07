"""PPTX -> PDF (LibreOffice). 한글·영문 사이 자동 간격(LibreOffice 전용 기능)을 끄고 내보낸다.
PowerPoint 에서 직접 PDF 로 저장해도 된다. 사용: python3 to_pdf.py in.pptx out.pdf"""
import subprocess, sys, time, os, uno
from com.sun.star.beans import PropertyValue

src, dst = map(os.path.abspath, sys.argv[1:3])
p = subprocess.Popen(["soffice", "--headless", "--invisible", "--norestore",
                      "--accept=socket,host=localhost,port=2002;urp;"])
ctx = None
for _ in range(60):
    try:
        lc = uno.getComponentContext()
        res = lc.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", lc)
        ctx = res.resolve("uno:socket,host=localhost,port=2002;urp;StarOffice.ComponentContext")
        break
    except Exception:
        time.sleep(0.5)
desk = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
def pv(n, v):
    x = PropertyValue(); x.Name = n; x.Value = v; return x
doc = desk.loadComponentFromURL(uno.systemPathToFileUrl(src), "_blank", 0, (pv("Hidden", True),))
def fix(shape):
    if shape.supportsService("com.sun.star.drawing.GroupShape"):
        for i in range(shape.getCount()): fix(shape.getByIndex(i))
        return
    if not hasattr(shape, "createEnumeration"):
        return
    try:
        e = shape.createEnumeration()
    except Exception:
        return
    while e.hasMoreElements():
        para = e.nextElement()
        try:
            para.ParaIsCharacterDistance = False
        except Exception:
            pass
pages = doc.getDrawPages()
for i in range(pages.getCount()):
    pg = pages.getByIndex(i)
    for j in range(pg.getCount()):
        fix(pg.getByIndex(j))
doc.storeToURL(uno.systemPathToFileUrl(dst), (pv("FilterName", "impress_pdf_Export"),))
doc.close(True)
try: desk.terminate()
except Exception: pass
p.wait(timeout=30)
