from pypdf import PdfReader
reader = PdfReader("NewCoC-QS_200228.pdf")
text = "\n".join(page.extract_text() or "" for page in reader.pages)
open("scenario.txt", "w", encoding="utf-8").write(text)