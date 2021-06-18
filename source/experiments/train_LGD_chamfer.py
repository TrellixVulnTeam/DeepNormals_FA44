import numpy as np
import torch 
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

from torch.utils.tensorboard import SummaryWriter

import sys
import os
sys.path.append( os.path.dirname( os.path.dirname( os.path.abspath(__file__) ) ) )

from loaders import PSGDataset
from models.LGD import LGD, detach_var
from evaluate_functions import chamfer_distance, nearest_from_to, dist_from_to

from knn import knn

from torch.utils.data import  DataLoader, WeightedRandomSampler

import argparse

from sklearn.neighbors import KDTree



def main():
    parser = argparse.ArgumentParser(description='Test',
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument('data', metavar='DATA', help='path to file')

    parser.add_argument('--tb-save-path', dest='tb_save_path', metavar='PATH', default='../checkpoints/', 
                            help='tensorboard checkpoints path')

    parser.add_argument('--weight-save-path', dest='weight_save_path', metavar='PATH', default='../weights/', 
                            help='weight checkpoints path')


    parser.add_argument('--batchsize', dest='batchsize', type=int, metavar='BATCHSIZE', default=1,
                            help='batch size')
    parser.add_argument('--epoch', dest='epoch', type=int,metavar='EPOCH', default=500, 
                            help='epochs for adam and lgd')
    parser.add_argument('--lr', dest='lr', type=float,metavar='LEARNING_RATE', default=1e-3, 
                            help='learning rate')
    parser.add_argument('--perturb', dest='perturb', type=float,metavar='PERTURBATION', default=1e-2, 
                            help='perturbation')
    parser.add_argument('--lgd-step', dest='lgd_step_per_epoch', type=int,metavar='LGD_STEP_PER_EPOCH', default=5, 
                            help='number of simulation steps of LGD per epoch')

    args = parser.parse_args()

    lr = args.lr
    epoch = args.epoch
    lgd_step_per_epoch = args.lgd_step_per_epoch
    batchsize = args.batchsize
    perturb = args.perturb

    writer = SummaryWriter(args.tb_save_path)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    
    ds = PSGDataset(args.data)
    dl = DataLoader(ds, batch_size=batchsize, shuffle=True)

    knn_f = knn.apply

    chamfer_dist = lambda x, y: knn_f(x, y, 1).mean() + knn_f(y, x, 1).mean()

    #chamfer_dist_list = lambda x: torch.cat([chamfer_dist(x[0][i * 1024 : (i+1)*1024], x_gt[i]).unsqueeze(0) for i in range(batchsize)]).mean()
    

    print("lgd")
    hidden = None

    lgd = LGD(3, 1, k=10).to(device)
    lgd_optimizer = optim.Adam(lgd.parameters(), lr= lr, weight_decay=1e-3)

    # train LGD
    lgd.train()
    for i in range(epoch):
        # evaluate losses
        sample_batched = next(iter(dl))

        x_gt = sample_batched['pc_gt'].reshape(-1,16384,3).to(device)

        ind = [torch.randperm(16384)[:512] for i in range(x_gt.shape[0])]

        x = torch.cat([x_gt[i][ind[i]].unsqueeze(0) for i in range(x_gt.shape[0])]).detach_()
        x += torch.randn_like(x) * perturb
        x.requires_grad_()

        validating = (1 - sample_batched['validating']).reshape(-1).to(device)

        chamfer_dist_list = lambda x: torch.cat([chamfer_dist(x[0][i], x_gt[i]).unsqueeze(0) * validating[i] for i in range(x_gt.shape[0])]).mean()
        
        # update lgd parameters
        lgd_optimizer.zero_grad()
        loss_sum, _, _ = lgd.loss_trajectory_backward(x, [chamfer_dist_list], None, 
                                     constraints=["None"], steps=lgd_step_per_epoch)
        
        lgd_optimizer.step()

        loss_sum.detach_()
        print(i, loss_sum.item())
        writer.add_scalars("train_loss", {"LGD": loss_sum}, global_step=i)
        torch.save(lgd.state_dict(), args.weight_save_path+'model_%03d.pth' % i)
        
    writer.close()

if __name__ == "__main__":
    main()
