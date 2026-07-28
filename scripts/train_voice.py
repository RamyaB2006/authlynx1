import os
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import torchaudio
import torchaudio.transforms as T
import soundfile as sf
from torch.utils.data import Dataset, DataLoader

class ASVspoofDataset(Dataset):
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.samples = []
        self.protocol_file = os.path.join(
            base_dir, "LA/ASVspoof2019_LA_cm_protocols/ASVspoof2019.LA.cm.train.trn.txt"
        )
        self.audio_dir = os.path.join(base_dir, "LA/ASVspoof2019_LA_train/flac")
        
        print(f"[INFO] Loading ASVspoof protocol from {self.protocol_file}")
        self._parse_protocol()

        # Define the Torchaudio MFCC transformer
        self.mfcc_transform = T.MFCC(
            sample_rate=16000,
            n_mfcc=40,
            melkwargs={"n_mels": 40, "n_fft": 400, "hop_length": 160, "mel_scale": "htk"}
        )

    def _parse_protocol(self):
        if not os.path.exists(self.protocol_file):
            print(f"[WARNING] Protocol file not found: {self.protocol_file}")
            return
            
        with open(self.protocol_file, 'r') as f:
            lines = f.readlines()
            print(f"[INFO] Found {len(lines)} entries in protocol file. Validating audio files...")
            
            for i, line in enumerate(lines):
                if i > 0 and i % 5000 == 0:
                    print(f"       Validated {i}/{len(lines)} protocol entries...")
                    
                parts = line.strip().split()
                if len(parts) < 5:
                    continue
                file_id = parts[1]
                attack_type = parts[3]
                key = parts[4]

                if key == 'bonafide':
                    label = 0  # Genuine
                elif attack_type in ['A01', 'A02', 'A03', 'A04']:
                    label = 2  # AI-generated
                else:
                    label = 1  # Replay

                audio_path = os.path.join(self.audio_dir, f"{file_id}.flac")
                if os.path.exists(audio_path):
                    self.samples.append((audio_path, label))
                    
        print(f"[INFO] Successfully loaded {len(self.samples)} valid audio samples.")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        path, label = self.samples[idx]
        
        # BULLETPROOF FIX: Use soundfile directly to bypass torchaudio.load and torchcodec
        audio_np, sr = sf.read(path)
        
        # Convert to float32 tensor and ensure [channels, time] dimensions
        waveform = torch.tensor(audio_np, dtype=torch.float32)
        if waveform.ndim == 1:
            waveform = waveform.unsqueeze(0)
        
        # Resample to 16000 if necessary
        if sr != 16000:
            resampler = T.Resample(orig_freq=sr, new_freq=16000)
            waveform = resampler(waveform)
            
        # Convert stereo to mono if necessary
        if waveform.shape[0] > 1:
            waveform = torch.mean(waveform, dim=0, keepdim=True)
            
        # Pad or truncate to exactly 3 seconds (48000 samples)
        target_length = 48000
        if waveform.shape[1] < target_length:
            pad_amount = target_length - waveform.shape[1]
            waveform = torch.nn.functional.pad(waveform, (0, pad_amount))
        elif waveform.shape[1] > target_length:
            waveform = waveform[:, :target_length]
            
        # Extract MFCC
        mfcc = self.mfcc_transform(waveform)
        
        # Normalize
        mfcc = (mfcc - mfcc.mean()) / (mfcc.std() + 1e-8)
        
        return mfcc, label

class VoiceSpoofCNN(nn.Module):
    def __init__(self):
        super(VoiceSpoofCNN, self).__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(1, 16, kernel_size=3, padding=1),
            nn.BatchNorm2d(16),
            nn.ReLU(),
            nn.MaxPool2d(2, 2),
            nn.Conv2d(16, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.MaxPool2d(2, 2)
        )
        self.fc = nn.Sequential(
            nn.AdaptiveAvgPool2d((1, 1)),
            nn.Flatten(),
            nn.Linear(32, 64),
            nn.ReLU(),
            nn.Linear(64, 3)
        )

    def forward(self, x):
        return self.fc(self.conv(x))

def train_voice_model():
    os.makedirs("./trained_models", exist_ok=True)
    dataset = ASVspoofDataset(base_dir="./datasets/ASVspoof2019_LA")
    if len(dataset) == 0:
        print("[ERROR] No audio samples found in official ASVspoof2019_LA protocol directory structure.")
        return

    # Use pin_memory and num_workers for faster torchaudio data loading
    loader = DataLoader(dataset, batch_size=16, shuffle=True, pin_memory=True)
    
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"[INFO] Initializing Voice Spoof CNN on device: {device}")
    
    model = VoiceSpoofCNN().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)

    model.train()
    for epoch in range(200):
        running_loss = 0.0
        for inputs, labels in loader:
            inputs, labels = inputs.to(device), labels.to(device)
            optimizer.zero_grad()
            outputs = model(inputs)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            running_loss += loss.item()
        print(f"Epoch {epoch+1}/200 Loss: {running_loss / len(loader):.4f}")

    torch.save(model.state_dict(), "./trained_models/voice_spoof_cnn.pth")
    print("[SUCCESS] Saved Voice Spoof CNN model to ./trained_models/voice_spoof_cnn.pth")

if __name__ == "__main__":
    train_voice_model()