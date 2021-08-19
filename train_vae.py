import warnings
warnings.filterwarnings("ignore", category=UserWarning) 
warnings.filterwarnings("ignore", category=RuntimeWarning)

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import torchvision
from torch.utils import data
import argparse
import numpy as np
import scipy
from scipy.stats import norm
#our libs
import matplotlib.pyplot as plt
import seaborn as sns
import utils
from utils import truncated_normal
from ot_modules.icnn import *
from gen_data import *
from torchvision import datasets, transforms, utils
from models import *

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

def loss_function(recon_x, x, mu, logvar):

    BCE = F.binary_cross_entropy(recon_x, x, reduction='sum')

    # see Appendix B from VAE paper:
    # Kingma and Welling. Auto-Encoding Variational Bayes. ICLR, 2014
    # https://arxiv.org/abs/1312.6114
    # 0.5 * sum(1 + log(sigma^2) - mu^2 - sigma^2)
    KLD = -0.5 * torch.sum(1 + logvar - mu.pow(2) - logvar.exp())

    return BCE + args.kl_scale * KLD

def plot2d(Y, name):
    Y = Y.detach().cpu().numpy()
    sns.kdeplot(Y[:, 0], Y[:, 1], cmap='Blues', shade=True, thresh=0)
    plt.savefig("./" + name)
    plt.clf()

def histogram(Y, name):
    Y = Y.detach().cpu().numpy()
    plt.hist(Y, bins=25)
    plt.savefig("./" + name)
    plt.clf()

def plotaxis(Y, name):
    y1, y2 = Y[:,0], Y[:,1]
    histogram(y1, name=str(name)+'_x1.png')
    histogram(y2, name=str(name)+'_x2.png')

def gaussian_mixture(means, stds, p, args):
    assert np.sum(p) == 1
    k = len(p)
    ranges = [0.]
    for i in range(k):
        ranges.append(ranges[i] + p[i])
    mix = np.zeros((args.n, 1))
    idx = np.random.uniform(0, 1, size=(args.n, 1))
    for i in range(k):
        g = np.random.normal(loc=means[i], scale=stds[i], size=(args.n, 1))
        indices = np.logical_and(idx >= ranges[i], idx < ranges[i+1])
        mix[indices] = g[indices]
    return mix

def optimizer(net, vae, args):
    assert args.optimizer.lower() in ["sgd", "adam"], "Invalid Optimizer"

    params = list(vae.parameters()) #+ list(vae.parameters())
    if args.optimizer.lower() == "sgd":
	       return optim.SGD(params, lr=args.lr, momentum=args.beta1, nesterov=args.nesterov)
    elif args.optimizer.lower() == "adam":
	       return optim.Adam(params, lr=args.lr, betas=(args.beta1, args.beta2))

def unif(size, eps=1E-7):
    return torch.clamp(torch.rand(size).cuda(), min=eps, max=1-eps)

def test(net, args, name, loader, vae):
    net.eval()
    vae.eval()

    '''
    for p in list(net.parameters()):
        if hasattr(p, 'be_positive'):
            print(p)
    '''
    #U = torch.rand(size=(args.n, args.dims), requires_grad=True).cuda()
    '''
    gauss = torch.distributions.normal.Normal(torch.tensor([0.]).cuda(), torch.tensor([1.]).cuda())
    U_ = unif(size=(64, args.dims))
    U = gauss.icdf(U_)
    U.requires_grad = True
    f = net.forward(U, grad=True).sum()
    Y_hat = torch.autograd.grad(f, U, create_graph=True)[0]
    Y_hat = vae.project(Y_hat).view(-1, vae.kernel_num, vae.feature_size, vae.feature_size)
    Y_hat = vae.decoder(Y_hat)
    '''
    #print("max and min points generated: " + str(Y_hat.max()) + " " + str(Y_hat.min()))
    Y_hat = vae.sample(64)
    print(Y_hat.max(), Y_hat.min(), Y_hat.mean())
    utils.save_image(utils.make_grid(Y_hat),
        './cifar.png')
    return
    if args.dims == 1:
        histogram(Y_hat, name) # uncomment for 1d case
    else:
        plot2d(Y_hat, name='imgs/2d.png') # 2d contour plot
        plotaxis(Y_hat, name='imgs/train')

positive_params = []

def dual(U, Y_hat, Y, eps=0):
    loss = torch.mean(Y_hat)
    Y = Y.permute(1, 0)
    psi = torch.mm(U, Y) - Y_hat
    sup, _ = torch.max(psi, dim=0)
    loss += torch.mean(sup)

    if eps == 0:
        return loss

    l = torch.exp((psi-sup)/eps)
    loss += eps*torch.mean(l)
    return loss

def train(net, optimizer, loader, vae, args):
    k = args.k
    gauss = torch.distributions.normal.Normal(torch.tensor([0.]).cuda(), torch.tensor([1.]).cuda())
    for epoch in range(1, args.epoch+1):
        running_loss = 0.0
        for idx, (x, label) in enumerate(loader):
            x = x.cuda()
            #u = unif(size=(args.batch_size, args.dims))
            #u = gauss.icdf(u)
            optimizer.zero_grad()
            #Y_hat = net(u)
            (mean, logvar), x_recon, z = vae(x)
            loss = vae.reconstruction_loss(x_recon, x) #+ dual(U=u, Y_hat=Y_hat, Y=z, eps=args.eps)
            loss += vae.kl_divergence_loss(mean, logvar)
            loss.backward()
            optimizer.step()
            #for p in positive_params:
            #	p.data.copy_(torch.relu(p.data))
            running_loss += loss.item()

        print('Epoch %d : %.5f' %
            (epoch, running_loss/(idx+1)))

    test(net, args, name='imgs/trained.png', loader=loader, vae=vae)
    '''
    Y = eg.sample(5000).cuda()
    plotaxis(Y, name='imgs/theor')
    plot2d(Y, name='imgs/theor.png')
    '''

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    # optimization related arguments
    parser.add_argument('--batch_size', default=128, type=int,
                        help='input batch size')
    parser.add_argument('--epoch', default=100, type=int,
                        help='epochs to train for')
    parser.add_argument('--optimizer', default='adam', help='optimizer')
    parser.add_argument('--lr', default=0.005, type=float, help='LR')
    parser.add_argument('--beta1', default=0.9, type=float,
                        help='momentum for sgd, beta1 for adam')
    parser.add_argument('--beta2', default=0.999, type=float)
    parser.add_argument('--nesterov', default=False)
    parser.add_argument('--iters', default=1000, type=int)
    parser.add_argument('--mean', default=0, type=int)
    parser.add_argument('--std', default=1, type=int)
    parser.add_argument('--dims', default=128, type=int)
    parser.add_argument('--m', default=10, type=int)
    parser.add_argument('--n', default=5000, type=int)
    parser.add_argument('--k', default=100, type=int)
    parser.add_argument('--genTheor', action='store_true')
    parser.add_argument('--gaussian_support', action='store_true')
    parser.add_argument('--eps', default=0, type=float)
    parser.add_argument('--kl_scale', default=1., type=float)
    args = parser.parse_args()

    print("Input arguments:")
    for key, val in vars(args).items():
        print("{:16} {}".format(key, val))

    torch.cuda.set_device('cuda:0')
    net = ICNN_LastInp_Quadratic(input_dim=args.dims,
                                 hidden_dim=512,#1024,#512
                                 activation='celu',
                                 num_layer=3)

    #net = icq(net_, gs=args.gaussian_support)
    vae = VAE(image_size=32,
            channel_num=3,
            kernel_num=128,
            z_size=args.dims)

    #for p in list(net.parameters()):
    #    if hasattr(p, 'be_positive'):
    #        positive_params.append(p)
    #    p.data = torch.from_numpy(truncated_normal(p.shape, threshold=1./np.sqrt(p.shape[1] if len(p.shape)>1 else p.shape[0]))).float()

    transform_train = transforms.Compose([
        transforms.RandomCrop(32, padding=4),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        ])
    trainset = torchvision.datasets.CIFAR10(root='./data', train=True, download=True, transform=transform_train)
    loader = torch.utils.data.DataLoader(trainset, batch_size=args.batch_size, shuffle=True, num_workers=0)
    optimizer = optimizer(net, vae, args)
    net.cuda()
    vae.cuda()
    train(net, optimizer, loader, vae, args)
    #mnist
    #train(net, optimizer, loader, ds.y[:args.n].float().cuda(), args)

    if args.genTheor:
        Y = torch.from_numpy(ds.y)
        plotaxis(Y, name='imgs/theor')
        plot2d(Y, name='imgs/theor.png')

    print("Training completed!")