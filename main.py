from core.security import verify_face
from core.brain import ask_simba
import time

def run_project():
    print("--- Welcome to Simba AI System ---")
    
    # Face Unlock
    if verify_face():
        print("Access Granted! Welcome Dhruv.")
        
        # main
        while True:
            query = input("\nYou: ") 
            
            if 'exit' in query or 'stop' in query:
                print("Simba: Goodbye Dhruv!")
                break
            
            # ans from ai
            print("Simba: Thinking...")
            answer = ask_simba(query)
            print(f"Simba: {answer}")
    else:
        print("Access Denied! Face not recognized.")

if __name__ == "__main__":
    run_project()