import os
import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

def train_behavioral_model():
    model_dir = "./trained_models"
    os.makedirs(model_dir, exist_ok=True)
    
    print("[INFO] Generating baseline behavioral biometrics dataset...")
    
    # Generate baseline distributions representing normal user interactions
    np.random.seed(42)
    
    # Typing features: speed, hold_time, latency, rhythm, error_rate
    typing_data = np.random.normal(
        loc=[180.0, 80.0, 120.0, 15.0, 0.02], 
        scale=[20.0, 10.0, 15.0, 3.0, 0.01], 
        size=(500, 5)
    )
    
    # Mouse features: movement_speed, click_frequency, scrolling_speed, acceleration
    mouse_data = np.random.normal(
        loc=[400.0, 2.5, 150.0, 1200.0], 
        scale=[50.0, 0.5, 20.0, 200.0], 
        size=(500, 4)
    )
    
    # Combine typing and mouse data horizontally (500 samples, 9 features)
    combined_features = np.hstack([typing_data, mouse_data])
    print(f"[INFO] Dataset generated successfully with shape: {combined_features.shape}")

    print("[INFO] Training Isolation Forest model for anomaly detection...")
    # Train Isolation Forest (contamination=0.05 means we expect 5% of future data to be anomalies/attacks)
    model = IsolationForest(n_estimators=100, contamination=0.05, random_state=42)
    model.fit(combined_features)

    # Save the trained model to disk
    save_path = os.path.join(model_dir, "behavioral_isolation_forest.pkl")
    joblib.dump(model, save_path)
    print(f"[SUCCESS] Saved Behavioral Isolation Forest model to {save_path}")

if __name__ == "__main__":
    train_behavioral_model()