"""Test the effect of unanticipated classes in Pseudo labelling on fashion_mnist (a semi-supervised method based on self-training).
And test methods to reduce the negative effect."""
import time
import csv
import os
import argparse
import errno

import torch
import torch.optim as optim
from torch.utils.data.sampler import BatchSampler, SubsetRandomSampler
from torchvision import transforms

# from utils import utils
from utils import data
from utils.utils import str2bool, alpha_ramp_up
import pseudo_label
from architectures import Net
from datasets import fashion_mnist


def main():
    # Training settings
    parser = argparse.ArgumentParser(description='PyTorch MNIST Example')
    parser.add_argument('--batch-size', type=int, default=100, metavar='N',
                        help='total batch size for training (default: 100)')
    parser.add_argument('--labeled-batch-size', type=int, default=50, metavar='N',
                        help='labeled input batch size (default: 50)')
    parser.add_argument('--n-labeled', type=int, default=100, metavar='N',
                        help='number of labelled data (default: 100)')
    parser.add_argument('--alpha', type=float, default=1, metavar='ALPHA',
                        help='Hyperparameter for the loss (default: 1)')
    parser.add_argument('--beta', type=float, default=1, metavar='BETA',
                        help='Hyperparameter for the distance to weight function (default: 1.0)')
    parser.add_argument('--pure', default=False, type=str2bool, metavar='BOOL',
                        help='Is the unlabelled data pure')
    parser.add_argument('--weights', default='none', choices=['encoding', 'raw', 'none'], type=str, metavar='S',
                        help='What weights to use.')
    parser.add_argument('--encoder', default=None, type=str, metavar='S',
                        help='File name for the pretrained autoencoder.')
    parser.add_argument('--dim', type=int, default=20, metavar='N',
                        help='The dimension of the encoding.')
    parser.add_argument('--output', default='default_ouput.csv', type=str, metavar='S',
                        help='File name for the output.')
    parser.add_argument('--exclude-unlabeled', default=False, type=str2bool, metavar='BOOL',
                        help='exclude unlabeled examples from the training set')
    parser.add_argument('--test-batch-size', type=int, default=1000, metavar='N',
                        help='input batch size for testing (default: 1000)')
    parser.add_argument('--epochs', type=int, default=50, metavar='N',
                        help='number of epochs to train (default: 10)')
    parser.add_argument('--lr', type=float, default=0.1, metavar='LR',
                        help='learning rate (default: 0.01)')
    parser.add_argument('--momentum', type=float, default=0.0, metavar='M',
                        help='SGD momentum (default: 0.0)')
    parser.add_argument('--gamma', type=float, default=1.0, metavar='GAMMA',
                        help='Gamma for learning rate decay (default: 1.0)')
    parser.add_argument('--no-cuda', action='store_true', default=False,
                        help='disables CUDA training')
    parser.add_argument('--seed', type=int, default=0, metavar='S',
                        help='random seed (default: 0)')
    parser.add_argument('--log-interval', type=int, default=10, metavar='N',
                        help='how many batches to wait before logging training status')
    parser.add_argument('--runs', type=int, default=10, metavar='N',
                        help='Number of runs')
    parser.add_argument('--save-model', action='store_true', default=False,
                        help='For Saving the current Model')
    args = parser.parse_args()
    torch.manual_seed(args.seed) # set seed for pytorch
    use_cuda = torch.cuda.is_available()

    wanted_classes = {0,1,2,3,4}
    args.num_classes = len(wanted_classes)

    folder = os.path.expanduser('./fashion_mnist_results')
    try:
        os.makedirs(folder)
    except OSError as e:
        if e.errno == errno.EEXIST:
            pass
        else:
            raise
    output_path = os.path.join(folder, args.output)


    for seed in range(args.runs): # seed for creating labelled and unlabelled data training data.

        device = torch.device("cuda" if use_cuda else "cpu")

        kwargs = {'num_workers': 1, 'pin_memory': True} if use_cuda else {}
        
        train_dataset = fashion_mnist.FashionMNIST('../fashion_mnist', dataset='train',
                                       weights=args.weights,
                                       encoder=args.encoder,
                                       n_labeled=args.n_labeled,
                                       wanted_classes=wanted_classes,
                                       pure=args.pure,
                                       download=True,
                                       transform=transforms.Compose([
                                       transforms.ToTensor()]),
                                       seed=seed,
                                       alpha=args.beta,
                                       func='exp',
                                       dim=args.dim)

        if args.exclude_unlabeled:
            sampler = SubsetRandomSampler(range(args.n_labeled))
            batch_sampler = BatchSampler(sampler, args.batch_size, drop_last=False)
        else:
            batch_sampler = data.TwoStreamBatchSampler(
                range(args.n_labeled, len(train_dataset)), range(args.n_labeled), args.batch_size, args.labeled_batch_size)

        train_loader = torch.utils.data.DataLoader(
            train_dataset,
            batch_sampler=batch_sampler,
            **kwargs)

        test_loader = torch.utils.data.DataLoader(
            fashion_mnist.FashionMNIST('../fashion_mnist', dataset='test', wanted_classes=wanted_classes, transform=transforms.Compose([
                transforms.ToTensor()])),
            batch_size=args.test_batch_size, shuffle=True, **kwargs)

        model = Net(args.num_classes).to(device)

        optimizer = optim.SGD(model.parameters(), lr=args.lr, momentum=args.momentum)
        lr_scheduler = optim.lr_scheduler.ExponentialLR(optimizer, gamma=args.gamma)
        for epoch in range(1, args.epochs + 1):
            alpha = alpha_ramp_up(args.alpha, epoch, 2, 30) #######################################################################
            if not args.exclude_unlabeled:
                pseudo_label.assign_labels(args, model, device, train_dataset, range(args.n_labeled, len(train_dataset)))
            
            start = time.time()
            pseudo_label.train(args, model, device, train_loader, optimizer, epoch, alpha)
            print('\nTraining one epoch took: {:.4f} seconds.\n'.format(time.time()-start))
            accuracy = pseudo_label.test(args, model, device, test_loader)
            lr_scheduler.step()

        with open(output_path, 'a') as writeFile:
            writer = csv.writer(writeFile)
            writer.writerow([seed, accuracy])


        if (args.save_model):
            torch.save(model.state_dict(),"fashion_mnist_cnn.pt")

if __name__ == '__main__':
    main()
