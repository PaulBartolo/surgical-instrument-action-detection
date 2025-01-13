import os
import sys
from pathlib import Path
import torch
import torch.nn as nn
import torchvision.transforms as transforms
import numpy as np
from sklearn.metrics import average_precision_score
import json
from PIL import Image, ImageDraw, ImageFont
from collections import defaultdict
from tqdm import tqdm
from ultralytics import YOLO
import pytorch_lightning as pl

# Get the current script's directory and navigate to project root
current_dir = Path(__file__).resolve().parent  # hei_chole/evaluation
hei_chole_dir = current_dir.parent  # hei_chole
domain_adaptation_dir = hei_chole_dir.parent  # domain_adaptation
project_root = domain_adaptation_dir.parent  # surgical-instrument-action-detection
hierarchical_dir = project_root / "models" / "hierarchical-surgical-workflow"

# Add paths to Python path
sys.path.append(str(project_root))
sys.path.append(str(hierarchical_dir))

# Debug printing to verify paths
print("\nPython Path:")
print("Current directory:", current_dir)
print("Project root:", project_root)
print("Hierarchical directory:", hierarchical_dir)
print("\nSystem path includes:")
for p in sys.path:
    print(f"- {p}")

# Now try the imports
try:
    from verb_recognition.models.SurgicalActionNet import SurgicalVerbRecognition
    print("\n✓ Successfully imported SurgicalVerbRecognition")
except ImportError as e:
    print(f"\n✗ Failed to import SurgicalVerbRecognition: {str(e)}")
    print("Check if the following path exists:")
    verb_recognition_path = hierarchical_dir / "verb_recognition"
    print(f"- {verb_recognition_path}")
    if verb_recognition_path.exists():
        print("Directory exists!")
        print("Contents:", list(verb_recognition_path.glob("*")))
    else:
        print("Directory does not exist!")

class ModelLoader:
    def __init__(self):
        self.project_root = project_root
        self.hierarchical_dir = hierarchical_dir
        self.setup_paths()

    def setup_paths(self):
        """Defines all important paths for the models"""
        # YOLO model path
        self.yolo_weights = self.hierarchical_dir / "Instrument-classification-detection" / "weights" / "instrument_detector" / "best_v35.pt"
        # Verb model path
        self.verb_model_path = self.hierarchical_dir / "verb_recognition/checkpoints/jumping-tree-47/last.ckpt"
        
        # Dataset path for HeiChole
        self.dataset_path = Path("/data/Bartscht/HeiChole")
        
        print(f"YOLO weights path: {self.yolo_weights}")
        print(f"Verb model path: {self.verb_model_path}")
        print(f"Dataset path: {self.dataset_path}")

        # Validate paths
        if not self.yolo_weights.exists():
            raise FileNotFoundError(f"YOLO weights not found at: {self.yolo_weights}")
        if not self.verb_model_path.exists():
            raise FileNotFoundError(f"Verb model checkpoint not found at: {self.verb_model_path}")
        if not self.dataset_path.exists():
            raise FileNotFoundError(f"Dataset not found at: {self.dataset_path}")

    def load_yolo_model(self):
        try:
            model = YOLO(str(self.yolo_weights))
            print("YOLO model loaded successfully")
            return model
        except Exception as e:
            print(f"Error details: {str(e)}")
            raise Exception(f"Error loading YOLO model: {str(e)}")

    def load_verb_model(self):
        try:
            model = SurgicalVerbRecognition.load_from_checkpoint(
                checkpoint_path=str(self.verb_model_path)
            )
            model.eval()
            print("Verb recognition model loaded successfully")
            return model
        except Exception as e:
            print(f"Error details: {str(e)}")
            raise Exception(f"Error loading verb model: {str(e)}")

class HierarchicalEvaluator:
    def __init__(self, yolo_model, verb_model, dataset_dir):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.yolo_model = yolo_model
        self.verb_model = verb_model.to(self.device)
        self.verb_model.eval()
        self.dataset_dir = dataset_dir
        
        self.transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])

    def load_ground_truth(self, video):
        """
        Loads binary ground truth annotations for instruments and actions from HeiChole dataset.
        
        :param video: Video identifier (e.g., "VID01")
        :return: Dictionary with frame annotations
        """
        labels_folder = os.path.join(self.dataset_dir, "Labels")
        json_file = os.path.join(labels_folder, f"{video}.json")
        
        print(f"Loading annotations from: {json_file}")
        
        # Simplified frame annotations without pairs
        frame_annotations = defaultdict(lambda: {
            'instruments': defaultdict(int),
            'verbs': defaultdict(int)
        })
        
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)
                frames = data.get('frames', {})
                
                print(f"\nDebug Information:")
                print(f"Total frames in JSON: {len(frames)}")
                
                # Sample the first frame to understand structure
                first_frame = list(frames.items())[0]
                print(f"\nExample frame structure:")
                print(json.dumps(first_frame[1], indent=2))
                
                processed_frames = 0
                frames_with_instruments = 0
                frames_with_actions = 0
                
                for frame_num, frame_data in frames.items():
                    frame_number = int(frame_num)
                    processed_frames += 1
                    
                    has_instruments = False
                    has_actions = False
                    
                    # Get binary instrument annotations
                    instruments = frame_data.get('instruments', {})
                    for instr_name, present in instruments.items():
                        # Binary: 1 if instrument is present (value > 0), 0 otherwise
                        if present > 0:
                            frame_annotations[frame_number]['instruments'][instr_name] = 1
                            has_instruments = True
                    
                    # Get binary action annotations
                    actions = frame_data.get('actions', {})
                    for action_name, present in actions.items():
                        # Binary: 1 if action is present (value > 0), 0 otherwise
                        if present > 0:
                            frame_annotations[frame_number]['verbs'][action_name] = 1
                            has_actions = True
                    
                    if has_instruments:
                        frames_with_instruments += 1
                    if has_actions:
                        frames_with_actions += 1
                
                print(f"\nProcessing Statistics:")
                print(f"Total frames processed: {processed_frames}")
                print(f"Frames with instruments: {frames_with_instruments}")
                print(f"Frames with actions: {frames_with_actions}")
                
                # Sample a few processed frames
                print("\nSample of processed frames:")
                sample_frames = list(frame_annotations.keys())[:3]
                for frame_num in sample_frames:
                    print(f"\nFrame {frame_num}:")
                    print("Instruments:", dict(frame_annotations[frame_num]['instruments']))
                    print("Actions:", dict(frame_annotations[frame_num]['verbs']))
                
                return frame_annotations
                
        except Exception as e:
            print(f"Error loading annotations: {str(e)}")
            raise

def main():
    try:
        # Initialize ModelLoader
        loader = ModelLoader()
        
        # Load models
        yolo_model = loader.load_yolo_model()
        verb_model = loader.load_verb_model()
        
        # Create evaluator
        evaluator = HierarchicalEvaluator(
            yolo_model=yolo_model,
            verb_model=verb_model,
            dataset_dir=str(loader.dataset_path)
        )
        
        # Test ground truth loading
        test_video = "VID01"
        print(f"\nTesting ground truth loading for {test_video}...")
        annotations = evaluator.load_ground_truth(test_video)
        
        # Print sample of loaded annotations
        print("\nSample of loaded annotations:")
        sample_frame = list(annotations.keys())[0]
        print(f"Frame {sample_frame}:")
        print("Instruments:", dict(annotations[sample_frame]['instruments']))
        print("Actions:", dict(annotations[sample_frame]['verbs']))
        
    except Exception as e:
        print(f"❌ Error during initialization or evaluation: {str(e)}")

if __name__ == '__main__':
    main()