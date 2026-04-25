import google.generativeai as genai

genai.configure(api_key="YOUR_GEMINI_API_KEY")

# Test 1: Can we list models?
for m in genai.list_models():
    print(m.name)

# Test 2: Can we generate?
model = genai.GenerativeModel("gemini-2.5-flash-lite")
print(model.generate_content("Say hello").text)