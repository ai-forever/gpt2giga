from examples.gemini.common import print_json, request_json

models = request_json("GET", "/models")
print("models:")
print_json(models)

first_name = models["models"][0]["name"] if models.get("models") else "models/GigaChat"
model_id = first_name.removeprefix("models/")

model = request_json("GET", f"/models/{model_id}")
print("\nmodel:")
print_json(model)
