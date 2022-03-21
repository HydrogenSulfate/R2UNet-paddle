import argparse
import os
import random

import matplotlib.pyplot as plt
import numpy as np
import paddle
import paddle.nn as nn
import paddle.nn.functional as F
import paddle.optimizer as optim
from paddle.io import DataLoader, Dataset
from paddle.vision import datasets, transforms
from PIL import Image
# from reprod_log import ReprodLogger
from sklearn.feature_extraction import image
from sklearn.metrics import auc, roc_curve
from tqdm import tqdm

from evaluation import *
from model import IterNet, R2UNet, UNet

device = paddle.set_device('gpu') if paddle.device.is_compiled_with_cuda() else paddle.set_device('cpu')
import warnings

warnings.filterwarnings("ignore")

trans_fn1 = transforms.Compose([
    # transforms.CenterCrop(512),
    # transforms.RandomRotation(180),
    transforms.ToTensor(),
])

# random image transformation to do image augmentation
trans_fn2 = transforms.Compose([
    # transforms.ToPILImage(),
    transforms.CenterCrop(512),
    transforms.RandomRotation(180),
    transforms.ColorJitter(brightness=0.1, contrast=0.1, saturation=0.1, hue=0.1),
    transforms.RandomHorizontalFlip(prob=0.5),
    transforms.RandomVerticalFlip(prob=0.5),
    transforms.ToTensor(),
])

class UNetDataset(Dataset):
    def __init__(self, root, transform=None):
        self.root = root
        self.transforms = transform
        seed = random.randint(0, 2**32)
        self.imgs_path = list(sorted(os.listdir(os.path.join(self.root,"images"))))
        self.imgs = []
        for path in self.imgs_path:
            img_path = os.path.join(self.root, "images", path)
            img = Image.open(img_path)
            # image augmentation
            random.seed(seed) 
            img = self.transforms(img)

            # randomly select patches from 20 training images
            img=paddle.transpose(img, perm=[1,2, 0])
            img=paddle.to_tensor(image.extract_patches_2d(img, (48, 48), max_patches=1000, random_state = 1))
            img=paddle.transpose(img, perm=[0,3,1,2])

            for i, sub_img in enumerate(img):
                self.imgs.append(sub_img)
        
        self.masks_path = list(sorted(os.listdir(os.path.join(self.root, "mask"))))
        self.masks = []
        for path in self.masks_path:
            mask_path = os.path.join(self.root, "mask", path)
            mask = Image.open(mask_path)
            random.seed(seed)
            mask = self.transforms(mask)

            # randomly select patches from 20 training images
            mask = paddle.transpose(mask, perm=[1, 2, 0])
            mask = paddle.to_tensor(image.extract_patches_2d(mask, (48, 48), max_patches=1000, random_state=1))
            mask= mask.unsqueeze(3)
            mask = paddle.transpose(mask, perm=[0,3,1,2])

            for i, sub_mask in enumerate(mask):
                self.masks.append(sub_mask)

        self.targets_path = list(sorted(os.listdir(os.path.join(self.root, "1st_manual"))))
        self.targets = []
        for path in self.targets_path:
            target_path = os.path.join(self.root, "1st_manual", path)
            target = Image.open(target_path)
            random.seed(seed)
            target = self.transforms(target)

            # randomly select patches from 20 training images
            target = paddle.transpose(target, perm=[1, 2, 0])
            target = paddle.to_tensor(image.extract_patches_2d(target, (48, 48), max_patches=1000, random_state=1))
            target = target.unsqueeze(3)
            target = paddle.transpose(target, perm=[0,3,1,2])

            for i, sub_target in enumerate(target):
                self.targets.append(sub_target)


    def __getitem__(self, idx):
        
        # seed so image and target have the same random tranform
        seed = random.randint(0, 2**32)

        img = self.imgs[idx]
        random.seed(seed)
        # img = trans_fn2(img)

        mask = self.masks[idx]
        random.seed(seed)
        # mask = trans_fn2(mask)

        target = self.targets[idx]
        random.seed(seed)
        # target = trans_fn2(target)

        # fig = plt.figure()
        # ax1 = fig.add_subplot(1,3,1)
        # ax1.imshow(img.permute((1,2,0)))
        # ax2 = fig.add_subplot(1,3,2)
        # ax2.imshow(torch.squeeze(mask), cmap="gray")
        # ax3 = fig.add_subplot(1,3,3)
        # ax3.imshow(torch.squeeze(target), cmap="gray")
        # plt.show()


        # return img.to(device), mask.to(device), target.to(device)
        return img, mask, target

    def __len__(self):

        return len(self.imgs)


class model:

    def __init__(self, args):
        
        self.model = args.model
        self.epoch = args.epoch
        self.lr = args.lr
        self.batch_s = args.batch_size
        self.data_path = args.dataset_path
        self.output = args.result_path


        if self.model == 'U-Net':
            self.network = UNet()
        elif self.model == 'R2U-Net':
            self.network = R2UNet()
        elif self.model == 'IterNet':
            self.network = IterNet()
            
    def train(self):
        self.network.to(device)
        self.network.train()

        optimizer = optim.Adam(learning_rate=self.lr, parameters=self.network.parameters())
        scheduler = optim.lr.CosineAnnealingDecay(learning_rate=self.lr, T_max=self.epoch, eta_min=0.00001)
        loss_fn = nn.BCELoss()

        for i in range(self.epoch):
            print('{} epoch {} {}'.format('=' * 10, i, '=' * 10))
            sum_loss = 0
            training_set = UNetDataset(self.data_path+'training', trans_fn1)
            validation_set = UNetDataset(self.data_path+'validation', trans_fn1)
            training_loader = DataLoader(training_set, batch_size=self.batch_s, shuffle=True)
            validation_loader = DataLoader(validation_set, batch_size=self.batch_s, shuffle=True)
            for img, mask, target in tqdm(training_loader):
                print("input:", img)

                predict = self.network(img)

                print("predict:", predict)

                if self.model == 'IterNet':
                    mask = mask.reshape(shape=[mask.size(0), -1])
                    target = target.reshape(shape=[target.size(0), -1])
                    loss = 0
                    for j in range(3):
                        iter_predict = predict[j].reshape(shape=[predict[j].size(0), -1])
                        iter_predict = iter_predict * mask.reshape(shaep=[mask.size(0), -1])

                        loss += loss_fn(iter_predict, target)

                    sum_loss += loss
                else:
                    predict = predict.reshape(shape=[predict.shape[0], -1])
                    predict = predict * mask.reshape(shape=[mask.shape[0], -1])
                    target = target.reshape(shape=[target.shape[0], -1])


                    loss = loss_fn(predict, target)
                    sum_loss += loss.item()

                optimizer.clear_grad()
                loss.backward()
                optimizer.step()

            scheduler.step()

            sum_loss /= 230
            print('loss: {}'.format(sum_loss))

            if i % 5 == 0:
                paddle.save(self.network.state_dict(), '{}{}{}.pdparams'.format(self.output,self.model, i))

            #Validation#
            results=[]
            self.network.eval()
            with paddle.no_grad():
                for i, (img, mask, target) in enumerate(validation_loader):
                    predict = self.network(img)
                    if self.model == 'IterNet':
                        predict = predict[-1]

                    predict = predict * mask
                    predict = (predict>=0.5).astype(np.uint8)
                    target = target * mask
                    target = target.astype(np.uint8)
                    predict = np.array(predict)
                    target = np.array(target)
                    TP = np.sum(np.logical_and(predict== 1, target == 1))  # true positive
                    TN = np.sum(np.logical_and(predict== 0, target == 0))  # true negative
                    FP = np.sum(np.logical_and(predict == 1, target == 0))  # false positive
                    FN = np.sum(np.logical_and(predict == 0, target == 1))  # false negative
                    AC = (TP + TN) / (TP + TN + FP + FN)  # accuracy
                    SE = (TP) / (TP + FN)  # sensitivity
                    SP = TN / (TN + FP)  # specificity
                    precision = TP / (TP + FP)
                    recall = TP / (TP + FN)
                    F1 = 2 * ((precision * recall) / (precision + recall))
                    fpr, tpr, _ = roc_curve(target.flatten(), predict.flatten())
                    AUC = auc(fpr, tpr)
                    results.append((F1, SE, SP, AC, AUC, precision, recall))
                F1, SE, SP, AC, AUC, precision, recall= map(list, zip(*results))
                print(f'[Validation] F1:{sum(F1)/len(F1):.4f}, Precision:{sum(precision)/len(precision):.4f}, Recall:{sum(recall)/len(recall):.4f}, AC: {sum(AC)/len(AC):.4f}, AUC : {sum(AUC)/len(AUC):.4f}')
        paddle.save(self.network.state_dict(), '{}{}.pdparams'.format(self.output, self.model))

    
    def test(self, show):
        '''
        run test set
        '''
        # load saved model
        self.network.to('cpu')
        self.network.load_dict(paddle.load('{}{}.pdparams'.format(self.output, self.model)))
        self.network.eval()

        # load test set
        self.imgs_path = list(sorted(os.listdir(self.data_path+'testing/images')))
        self.masks_path = list(sorted(os.listdir(self.data_path + 'testing/mask')))
        self.targets_path = list(sorted(os.listdir(self.data_path+'testing/1st_manual')))
        
        results = []
        with paddle.no_grad():
            for img_name, mask_name, target_name in zip(self.imgs_path, self.masks_path, self.targets_path):
                img_path = os.path.join(self.data_path+'testing/images', img_name)
                img = Image.open(img_path)
                img = transforms.functional.center_crop(img, 560)
                img = transforms.functional.to_tensor(img).unsqueeze(0)

                mask_path = os.path.join(self.data_path+'testing/mask', mask_name)
                mask = Image.open(mask_path)
                mask = transforms.functional.center_crop(mask, 560)
                mask = np.array(mask).flatten() / 255
                mask = mask.astype(np.uint8)


                target_path = os.path.join(self.data_path+'testing/1st_manual', target_name)
                target = Image.open(target_path)
                target = transforms.functional.center_crop(target, 560)
                target = np.array(target)
                target_ = target.flatten() / 255
                target_ = target_.astype(np.uint8)
                target_ = target_[mask==1]

                predict = self.network(img)
                if self.model == 'IterNet':
                    predict = predict[-1]
                predict = np.squeeze(predict.numpy(), axis=(0,1))
                predict_ = predict.flatten()[mask==1]
                predict_ = (predict_>=0.5).astype(np.uint8)


                TP = np.sum(np.logical_and(predict_ == 1, target_ == 1)) # true positive
                TN = np.sum(np.logical_and(predict_ == 0, target_ == 0)) # true negative
                FP = np.sum(np.logical_and(predict_ == 1, target_ == 0)) # false positive
                FN = np.sum(np.logical_and(predict_ == 0, target_ == 1)) # false negative

                AC = (TP+TN)/(TP+TN+FP+FN) # accuracy
                SE = (TP)/(TP+FN) # sensitivity
                SP = TN/(TN+FP) # specificity
                precision = TP/(TP+FP)
                recall = TP/(TP+FN)
                F1 = 2*((precision*recall)/(precision+recall))
                fpr, tpr, _ = roc_curve(target_, predict_)
                AUC = auc(fpr,tpr)
                results.append((F1, SE, SP, AC, AUC))

                # show predicted image
                if show:
                    fig = plt.figure()
                    ax1 = fig.add_subplot(1,3,1)
                    ax1.imshow(img.squeeze(0).permute((1,2,0)))
                    ax2 = fig.add_subplot(1,3,2)
                    ax2.imshow(predict, cmap="gray")
                    ax3 = fig.add_subplot(1,3,3)
                    ax3.imshow(target, cmap="gray")
                    plt.show()

        F1, SE, SP, AC, AUC = map(list, zip(*results))

        print('F1 score: %.4f' %(sum(F1)/len(F1)))
        print('sensitivity: %.4f' %(sum(SE)/len(SE)))
        print('specificity: %.4f' %(sum(SP)/len(SP)))
        print('accuracy: %.4f' %(sum(AC)/len(AC)))
        print('AUC: %.4f' %(sum(AUC)/len(AUC)))

    def save_model(self):
        self.network.to(device)
        self.network.train()
        print(self.network)
        paddle.save(self.network.state_dict(), 'model_paddle.pdparams')

    def show_pkl(self):
        path_paddle = "./model_paddle.pdparams"
        paddle_dict = paddle.load(path_paddle)


        for key in paddle_dict:
            print(key)

    def forward_paddle(self):
        paddle.set_device("gpu")
        np.random.seed(0)
        paddle.seed(0)
        reprod_logger = ReprodLogger()
        self.network.load_dict(paddle.load("./R2U-Net.pth"))
        self.network.eval()
        # read or gen fake data
        fake_data = np.load("../fake_data.npy")
        fake_data = paddle.to_tensor(fake_data)
        # forward
        out = self.network(fake_data)
        print(out)
        reprod_logger.add("out", out.cpu().detach().numpy())
        reprod_logger.save("../diff/forward_paddle.npy")


    def metric_paddle(self):
        paddle.set_device("gpu")
        random.seed(0)
        np.random.seed(0)
        paddle.seed(0)
        # reprod_logger = ReprodLogger()
        self.network.load_dict(paddle.load("./R2U-Net.pdparams"))
        self.network.eval()

        with paddle.no_grad():
            img = np.load("../fake_img.npy")
            img = Image.fromarray(img)
            target = np.load("../fake_target.npy")
            target = Image.fromarray(target)

            img = transforms.CenterCrop(560)(img)
            img = transforms.ToTensor()(img).unsqueeze(0)
            target = transforms.CenterCrop(560)(target)
            target = np.array(target)
            target_ = target.flatten() / 255
            target_ = target_.astype(np.uint8)
            target_ = target_
            print(f"python infer img.shape={img.shape} target_.shape={target_.shape}")
            predict = self.network(img)

            print(f"python infer predict.shape={predict.shape}")
            predict = np.squeeze(predict.numpy(), axis=(0, 1))
            predict_ = predict.flatten()
            predict_ = (predict_ >= 0.5).astype(np.uint8)

            TP = np.sum(np.logical_and(predict_ == 1, target_ == 1))  # true positive
            TN = np.sum(np.logical_and(predict_ == 0, target_ == 0))  # true negative
            FP = np.sum(np.logical_and(predict_ == 1, target_ == 0))  # false positive
            FN = np.sum(np.logical_and(predict_ == 0, target_ == 1))  # false negative

            AC = (TP + TN) / (TP + TN + FP + FN)  # accuracy
            SE = (TP) / (TP + FN)  # sensitivity
            SP = TN / (TN + FP)  # specificity
            precision = TP / (TP + FP)
            recall = TP / (TP + FN)
            F1 = 2 * ((precision * recall) / (precision + recall))
            fpr, tpr, _ = roc_curve(target_, predict_)
            AUC = auc(fpr, tpr)
            print('F1 score:', F1)
            # reprod_logger.add("F1", np.array(F1))
        # reprod_logger.save("../diff/metric_paddle.npy")

    def _trans(self, path_to_checkpoint_file):
        # import argparse
        # import os
        # from os import path as osp

        # import paddle
        # from paddle import inference
        # from paddle.inference import Config, create_predictor
        from paddle.jit import to_static
        from paddle.static import InputSpec
        # from paddle.vision import transforms
        # from paddlevideo.utils import get_config
        print(f"Loading params from ({path_to_checkpoint_file})...")
        params = paddle.load(path_to_checkpoint_file)
        self.network.set_dict(params)

        self.network.eval()

        input_spec = InputSpec(shape=[None, 3, 560, 560],
                            dtype='float32',
                            name='input'),
        self.network = to_static(self.network, input_spec=input_spec)
        paddle.jit.save(self.network, "inference")
        print(f"model (R2UNet) has been already saved in (inference).")

    def _infer_static(self, model_file, params_file):
        from paddle.inference import Config, create_predictor
        config = Config(model_file, params_file)
        config.enable_use_gpu(8000, 0)
        config.switch_ir_optim(True)
        config.enable_memory_optim()
        config.switch_use_feed_fetch_ops(False)
        predictor = create_predictor(config)

        input_names = predictor.get_input_names()
        output_names = predictor.get_output_names()
        input_tensor_list = []
        output_tensor_list = []
        for item in input_names:
            input_tensor_list.append(predictor.get_input_handle(item))
        for item in output_names:
            output_tensor_list.append(predictor.get_output_handle(item))
        outputs = []

        img = np.load("../fake_img.npy")
        img = Image.fromarray(img)
        target = np.load("../fake_target.npy")
        target = Image.fromarray(target)

        img = transforms.CenterCrop(560)(img)
        img = transforms.ToTensor()(img).unsqueeze(0)
        target = transforms.CenterCrop(560)(target)
        target = np.array(target)
        target_ = target.flatten() / 255
        target_ = target_.astype(np.uint8)
        target_ = target_
        img = img.numpy()
        print(f"python infer img.shape={img.shape} target_.shape={target_.shape}")

        for i in range(len(input_tensor_list)):
            input_tensor_list[i].copy_from_cpu(img)
        predictor.run()
        for j in range(len(output_tensor_list)):
            outputs.append(output_tensor_list[j].copy_to_cpu())
        # print(len(outputs)) # 1
        # exit(0)
        predict = outputs[0]
        print(f"python infer predict.shape={predict.shape}")
        predict = np.squeeze(predict, axis=(0, 1))
        predict_ = predict.flatten()
        predict_ = (predict_ >= 0.5).astype(np.uint8)

        TP = np.sum(np.logical_and(predict_ == 1, target_ == 1))  # true positive
        TN = np.sum(np.logical_and(predict_ == 0, target_ == 0))  # true negative
        FP = np.sum(np.logical_and(predict_ == 1, target_ == 0))  # false positive
        FN = np.sum(np.logical_and(predict_ == 0, target_ == 1))  # false negative

        AC = (TP + TN) / (TP + TN + FP + FN)  # accuracy
        SE = (TP) / (TP + FN)  # sensitivity
        SP = TN / (TN + FP)  # specificity
        precision = TP / (TP + FP)
        recall = TP / (TP + FN)
        F1 = 2 * ((precision * recall) / (precision + recall))
        fpr, tpr, _ = roc_curve(target_, predict_)
        AUC = auc(fpr, tpr)
        print('F1 score:', F1)


    def loss_paddle(self):
        paddle.set_device("gpu")
        np.random.seed(0)
        paddle.seed(0)
        reprod_logger = ReprodLogger()
        self.network.load_dict(paddle.load("./R2U-Net.pdparams"))
        self.network.eval()
        # read or gen fake data
        fake_data = np.load("../fake_data.npy")
        fake_data = paddle.to_tensor(fake_data)
        fake_label = np.load("../fake_label.npy")
        fake_label = paddle.to_tensor(fake_label)

        predict = self.network(fake_data)
        predict = predict.reshape(shape=[predict.shape[0], -1])
        fake_label = fake_label.reshape(shape=[fake_label.shape[0], -1])
        loss_fn = nn.BCELoss()
        loss = loss_fn(predict, fake_label)

        print("loss:", loss)
        reprod_logger.add("loss", loss.cpu().detach().numpy())
        reprod_logger.save("../diff/loss_paddle.npy")

    def bp_align_paddle(self):
        paddle.set_device("gpu")
        np.random.seed(0)
        paddle.seed(0)
        reprod_logger = ReprodLogger()
        self.network.load_dict(paddle.load("./R2U-Net.pdparams"))
        self.network.train()
        # read or gen fake data
        fake_data = np.load("../fake_data.npy")
        fake_label = np.load("../fake_label.npy")
        loss_list = []

        optimizer = optim.Adam(learning_rate=self.lr, parameters=self.network.parameters())
        scheduler = optim.lr.CosineAnnealingDecay(learning_rate=self.lr, T_max=self.epoch, eta_min=0.00001)

        for idx in range(4):
            fake_data = paddle.to_tensor(fake_data)
            fake_label = paddle.to_tensor(fake_label)

            predict = self.network(fake_data)
            predict = predict.reshape(shape=[predict.shape[0], -1])
            fake_label = fake_label.reshape(shape=[fake_label.shape[0], -1])
            loss_fn = nn.BCELoss()
            loss = loss_fn(predict, fake_label)
            loss.backward()
            optimizer.step()
            # scheduler.step()
            optimizer.clear_grad()
            print("lr:", scheduler.get_lr())
            loss_list.append(loss.cpu().detach().numpy())
        print(loss_list)
        reprod_logger.add("loss_list[0]", np.array(loss_list[0]))
        reprod_logger.add("loss_list[1]", np.array(loss_list[1]))
        reprod_logger.add("loss_list[2]", np.array(loss_list[2]))
        reprod_logger.save("../diff/bp_align_paddle.npy")


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='U-Net')
    # general setting
    parser.add_argument('--model', type=str, default='R2U-Net', help='U-Net R2U-Net IterNet')
    parser.add_argument('--mode', type=str, default='train', help='train test')
    parser.add_argument('--dataset_path', type=str, default='./DRIVE/', help='dataset path')
    parser.add_argument('--result_path', type=str, default='./', help='path to save output')
    # training setting
    parser.add_argument('--epoch', type=int, default=45, help='training epoch')
    parser.add_argument('--lr', type=float, default=0.001, help='learning rate')
    parser.add_argument('--batch_size', type=int, default=1, help='batch size')
    # testing setting
    parser.add_argument('--show', type=str, default='False', help='if show the predicted image')
    args = parser.parse_args()

    m = model(args)

    ####################
    # m.save_model()
    # m.show_pkl()
    # m.forward_paddle()
    # m.loss_paddle()
    # m.metric_paddle()
    m._trans("./R2U-Net.pdparams")
    # model_file = '/workspace/hesensen/R2UNet-paddle/R2UNet_paddle/inference.pdmodel'
    # params_file = model_file.replace(".pdmodel", '.pdiparams')

    # m._infer_static(model_file, params_file)
    # m.bp_align_paddle()
    #####################



    # if args.mode == 'train':
    #     m.train()
    # else:
    #     if args.show == 'True':
    #         m.test(True)
    #     else:
    #         m.test(False)
