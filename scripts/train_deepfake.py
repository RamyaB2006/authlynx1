import os
import cv2
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms, models
from facenet_pytorch import MTCNN
from PIL import Image

class FaceForensicsDataset(Dataset):
    def __init__(self, root_dir, transform=None):
        self.root_dir = root_dir
        self.transform = transform
        self.samples = []
        
        # Enforce GPU usage for MTCNN if available
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        print(f"[INFO] Initializing MTCNN on device: {self.device}")
        
        self.mtcnn = MTCNN(keep_all=False, select_largest=True, post_process=False, device=self.device)
        self._prepare_dataset()

    def _prepare_dataset(self):
        temp_crop_dir = "./datasets/cropped_frames"
        os.makedirs(temp_crop_dir, exist_ok=True)
        categories = {'real': 0, 'fake': 1}

        print("[INFO] Starting video frame extraction and face cropping...")

        for cat, label in categories.items():
            cat_path = os.path.join(self.root_dir, cat)
            if not os.path.exists(cat_path):
                print(f"[WARNING] Directory not found: {cat_path}")
                continue
            
            video_files = [f for f in os.listdir(cat_path) if f.endswith(('.mp4', '.avi'))]
            print(f"[INFO] Found {len(video_files)} videos in '{cat}' category.")

            for i, video_file in enumerate(video_files):
                if i > 0 and i % 10 == 0:
                    print(f"       Processing {cat} video {i}/{len(video_files)}: {video_file}...")
                
                video_path = os.path.join(cat_path, video_file)
                cap = cv2.VideoCapture(video_path)
                frame_idx = 0
                
                while cap.isOpened():
                    ret, frame = cap.read()
                    if not ret or frame_idx > 10:  # Sample up to 10 frames per video
                        break
                    if frame_idx % 3 == 0:
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        pil_img = Image.fromarray(rgb)
                        result = self.mtcnn.detect(pil_img)
                        boxes = result[0]
                        if boxes is not None:
                            # Explicitly define as a 4-element float tuple for Pylance
                            b = boxes[0]
                            box = (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
                            cropped = pil_img.crop(box)
                            save_path = os.path.join(temp_crop_dir, f"{cat}_{video_file}_{frame_idx}.jpg")
                            cropped.save(save_path)
                            self.samples.append((save_path, label))
                    frame_idx += 1
                cap.release()
                
        print(f"[INFO] Preprocessing complete. Successfully extracted {len(self.samples)} face crops.")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        img_path, label = self.samples[idx]
        img = Image.open(img_path).convert('RGB')
        if self.transform:
            img = self.transform(img)
        return img, label

def train_mobilenet():
    os.makedirs("./trained_models", exist_ok=True)
    transform = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])

    dataset = FaceForensicsDataset(root_dir="./datasets/FaceForensics++", transform=transform)
    if len(dataset) == 0:
        print("[ERROR] No samples processed. Ensure FaceForensics++ mp4 videos exist in ./datasets/FaceForensics++/")
        return

    loader = DataLoader(dataset, batch_size=16, shuffle=True)
    
    model = models.mobilenet_v3_small(weights=models.MobileNet_V3_Small_Weights.DEFAULT)
    
    # Safely extract in_features using getattr to bypass Pylance strict typing
    in_features = int(getattr(model.classifier[3], "in_features"))
    model.classifier[3] = nn.Linear(in_features, 2)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = model.to(device)
    print(f"[INFO] Starting training MobileNetV3 on {device}...")

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

    torch.save(model.state_dict(), "./trained_models/deepfake_mobilenetv3.pth")
    print("[SUCCESS] Saved Deepfake MobileNetV3 model to ./trained_models/deepfake_mobilenetv3.pth")

if __name__ == "__main__":
    train_mobilenet()