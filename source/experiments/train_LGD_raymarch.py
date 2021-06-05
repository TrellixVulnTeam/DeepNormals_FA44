import numpy as np
import torch 
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

from torch.utils.tensorboard import SummaryWriter

import sys
import os
sys.path.append( os.path.dirname( os.path.dirname( os.path.abspath(__file__) ) ) )

from models.models import Siren
from loaders import ObjDataset, ObjUniformSample, Dataset, UniformSample, GridDataset, PointTransform
from models.LGD import LGD, detach_var

from torch.utils.data import  DataLoader, WeightedRandomSampler

import argparse


def main():
    parser = argparse.ArgumentParser(description='Test',
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument('data', metavar='DATA', help='path to file')

    parser.add_argument('--tb-save-path', dest='tb_save_path', metavar='PATH', default='../checkpoints/', 
                            help='tensorboard checkpoints path')

    parser.add_argument('--weight-save-path', dest='weight_save_path', metavar='PATH', default='../weights/', 
                            help='weight checkpoints path')

    parser.add_argument('--sdf-weight', dest='sdf_weight', metavar='PATH', default=None, 
                            help='pretrained weight for SDF model')


    parser.add_argument('--batchsize', dest='batchsize', type=int, metavar='BATCHSIZE', default=1,
                            help='batch size')
    parser.add_argument('--epoch', dest='epoch', type=int,metavar='EPOCH', default=500, 
                            help='epochs for adam and lgd')
    parser.add_argument('--lr', dest='lr', type=float,metavar='LEARNING_RATE', default=5e-3, 
                            help='learning rate')
    parser.add_argument('--lgd-step', dest='lgd_step_per_epoch', type=int,metavar='LGD_STEP_PER_EPOCH', default=5, 
                            help='number of simulation steps of LGD per epoch')

    parser.add_argument('--width', dest='width', type=int,metavar='WIDTH', default=128, 
                            help='width for rendered image')
    parser.add_argument('--height', dest='height', type=int,metavar='HEIGHT', default=128, 
                            help='height for rendered image')

    parser.add_argument('--outfile', dest='outfile', metavar='OUTFILE', 
                            help='output file')

    args = parser.parse_args()

    width = args.width
    height = args.height
    lr = args.lr
    epoch = args.epoch
    lgd_step_per_epoch = args.lgd_step_per_epoch

    writer = SummaryWriter(args.tb_save_path)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    # create models
    model = Siren(in_features=3, out_features=1, hidden_features=256, hidden_layers=5, outermost_linear=True).to(device) 

    if args.sdf_weight != None:
        try:
            model.load_state_dict(torch.load(args.sdf_weight))
        except:
            print("Couldn't load pretrained weight: " + args.sdf_weight)

    model.eval() 
    for param in model.parameters():
        param.requires_grad = False

    
    # load 
    mm = torch.tensor([-0.1, -0.1, 0.1], device=device, dtype=torch.float)
    mx = torch.tensor([0.1, 0.1, 0.1], device=device, dtype=torch.float)
    wh = torch.tensor([width, height, 1], device=device, dtype=torch.int)

    rot = torch.tensor([[1,0,0], [0,1,0], [0,0,1]], device=device, dtype=torch.float)
    trans = torch.tensor([[0, 0, -0.8]], device=device, dtype=torch.float)

    p_distribution = GridDataset(mm, mx, wh)

    d = torch.zeroes((width*height, 1), device=device, dtype=torch.float).requires_grad_(True)
    

    sampler = nn.Sequential(UniformSample(width*height), 
                            PointTransform(rot))

    p = sampler(p_distribution)


    ds = ObjDataset(args.data)
    objsampler = ObjUniformSample(1000)
    x_preview = (objsampler(ds)['p']).to(device)


    d2_eval = lambda d: torch.pow(d, 2).mean()
    sdf_eval = lambda d: torch.pow(model(d * ray_n + p + trans)[0], 2).sum(dim=1).mean()
    d_eval = lambda d: (torch.tanh(d) - 1.).mean() * 0.5

    d2_eval_list = lambda d: d2_eval(d[0])
    sdf_eval_list = lambda d: sdf_eval(d[0])
    d_eval_list = lambda d: d_eval(d[0])


    writer.add_mesh("preview", torch.cat([(p + trans),  x_preview]).unsqueeze(0), global_step=0)

    print("lgd")
    hidden = None

    lgd = LGD(1, 3, k=10).to(device)
    lgd_optimizer = optim.Adam(lgd.parameters(), lr= lr)

    # train LGD
    lgd.train()
    for i in range(epoch):
        print(i)
        # evaluate losses
        samples_n = width*height//128
        sample_inds = torch.randperm(width*height)[:samples_n]

        ray_n = torch.tensor([[0,0,1]], device=device, dtype=torch.float).repeat(samples_n, 1)

        sdf_eval_batch = lambda d: torch.pow(model(d * ray_n + p[sample_inds] + trans)[0], 2).sum(dim=1).mean()
        sdf_eval_batch_list = lambda d: sdf_eval_batch(d[0])

        # update lgd parameters
        lgd_optimizer.zero_grad()
        lgd.loss_trajectory_backward(d[sample_inds], [d2_eval_list, sdf_eval_batch_list, d_eval_list], None, 
                                     constraints=["None", "Zero", "Positive"], batch_size=samples_n, steps=lgd_step_per_epoch)
        lgd_optimizer.step()

        torch.save(lgd.state_dict(), args.weight_save_path+'model_%03d.pth' % i)
 
    writer.close()

if __name__ == "__main__":
    main()
