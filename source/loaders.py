import numpy as np
import cv2
import torch 
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import  Dataset, DataLoader
import re
import warnings

from torch.utils.tensorboard import SummaryWriter
import argparse



class ObjDataset(Dataset):

    @torch.no_grad()
    def __init__(self, obj_path):
        # read an obj file
        obj_file = open(obj_path, 'r')
        obj = obj_file.read()
        obj_file.close()

        # wish we could do "v %f %f %f" and "f %d %d %d" lol
        vpattern = r"(?:v)\s+([-\d\.e]+)\s+([-\d\.e]+)\s+([-\d\.e]+)"
        fpattern = r"(?:f)\s+(\d+)(?:\/\d*){0,2}\s+(\d+)(?:\/\d*){0,2}\s+(\d+)(?:\/\d*){0,2}"

        v = re.findall(vpattern, obj)
        f = re.findall(fpattern, obj)

        v = torch.tensor([list(map(float, v_)) for v_ in v], dtype=torch.float)
        f = torch.tensor([list(map(lambda x: int(x)-1, f_)) for f_ in f], dtype=torch.long)     # index starts from 1 in obj, so substract 1

        vf = v[f]

        # obtain face normal with cross vector
        a1 = - vf[:,0] + vf[:,1] 
        a2 = - vf[:,0] + vf[:,2]
        
        fn = torch.cat([t.unsqueeze(1) for t in 
           [a1[:,1] * a2[:,2] - a1[:,2] * a2[:,1],
            a1[:,2] * a2[:,0] - a1[:,0] * a2[:,2],
            a1[:,0] * a2[:,1] - a1[:,1] * a2[:,0]]], dim=1)

        # normalization
        fn = fn / torch.norm(fn, dim=1, keepdim=True)
        fn = torch.where(torch.isnan(fn), torch.zeros_like(fn), fn)

        vn = torch.zeros_like(v)

        # add face normal to connected vertices
        vn = vn.index_add(0, f.view(-1), fn.repeat(1,3).view(-1,3))

        # normalization
        vn = vn / torch.norm(vn, dim=1, keepdim=True)
        vn = torch.where(torch.isnan(vn), torch.zeros_like(vn), vn)
    
        self.v = v
        self.f = f
        self.vn = vn
        self.fn = fn

    def __len__(self):
        return len(self.v)

    def __getitem__(self, idx):
        return {'xyz': self.v[idx], 'n': self.vn[idx]}

    def to_obj(self):
        obj_file = open("../../../data/test.obj", 'w')

        for v in self.v:
            obj_file.write(f"v {v[0]} {v[1]} {v[2]}\n")
        
        for f in self.f:
            obj_file.write(f"f {f[0]+1} {f[1]+1} {f[2]+2}\n")

        for vn in self.vn:
            obj_file.write(f"vn {vn[0]} {vn[1]} {vn[2]}\n")

        #obj = obj_file.read()
        obj_file.close()
