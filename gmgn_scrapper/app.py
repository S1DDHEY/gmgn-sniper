from fastapi import FastAPI, HTTPException
import uvicorn

app = FastAPI()

@app.get("/")
async def get_text():
    """
    Reads the content of a text file and returns only the last line as JSON.
    Replace './data/new_coins.txt' with the path to your file.
    """
    try:
        with open("./data/new_coins.txt", "r") as file:
            lines = file.readlines()
            # Check if the file has any lines
            last_line = lines[-1].strip() if lines else "File is empty."
        return {"last_line": last_line}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
