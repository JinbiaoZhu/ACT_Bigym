import random
import PIL

import numpy as np
from torch.utils.data import Dataset
from torchvision.transforms import transforms

from buffer import ReplayBuffer
from tools import load_demo_dataset


def get_demo_dataset(args):
    # 从下载的数据集中载入指定数量的轨迹
    trajectories = load_demo_dataset(args.demo_path, num_traj=args.num_queries, concat=False)

    # 设置回放存储列表
    rb_list = []

    # 对轨迹集合中的每一条数据提取观测信息和动作信息
    for single_obs_traj, single_act_traj in zip(trajectories["observations"], trajectories["actions"]):

        # 定义经验回放池, 也就是存储状态转移的容器 (s, a, r, s', r, d) , 实际数据集从这里索引即可！
        rb = ReplayBuffer(
            proprioception_shape=(
                single_obs_traj["agent"]["qpos"].shape[1] + single_obs_traj["agent"]["qvel"].shape[1],
            ),
            obs_shape=(3, 128, 128),
            action_shape=(single_act_traj.shape[1],),
            capacity=300,
            device="cpu"
        )

        # 对每一条轨迹提取单步状态转移
        for t in range(1, single_obs_traj["agent"]["qpos"].shape[0]):
            pro = np.concatenate(
                [single_obs_traj["agent"]["qpos"][t - 1, :], single_obs_traj["agent"]["qvel"][t - 1, :]], 0
            )
            obs = single_obs_traj["sensor_data"]["base_camera"]["rgb"][t - 1].reshape((3, 128, 128))
            action = single_act_traj[t - 1]
            next_pro = np.concatenate(
                [single_obs_traj["agent"]["qpos"][t, :], single_obs_traj["agent"]["qvel"][t, :]], axis=0
            )
            next_obs = single_obs_traj["sensor_data"]["base_camera"]["rgb"][t].reshape((3, 128, 128))
            # done = demo.timesteps[t].termination or demo.timesteps[t].truncation
            rb.add(pro, obs, action, 0.0, next_pro, next_obs, 0.0)

        # 将经验回放池加入至回放存储列表中
        rb_list.append(rb)

    print("Put the demo dataset to the replay buffer")
    return rb_list


def get_dataset_index(rb_list, args):
    """
    获取用于训练、验证和测试的数据集索引
    """
    for rb in rb_list:
        if rb.idx <= args.context_length:
            continue
        total = rb.idx - args.context_length  # 表示整个数据集可被索引的范围
        scale = args.scale if total > args.scale else total
        indices = random.sample(range(total), scale)  # 随机选择 args.scale 个不同的索引
        # 计算每个部分的大小
        part1_size = int(scale * args.train_split)
        # 划分索引列表
        rb.train_index = indices[:part1_size]
        rb.valid_index = indices[part1_size:]

    print("The demo dataset in the replay buffer has been split.")


def get_dataset(args):
    rb_list = get_demo_dataset(args)
    get_dataset_index(rb_list, args)
    train_set = {"image_datas": [], "proprioception_datas": [], "action_sequences": []}
    valid_set = {"image_datas": [], "proprioception_datas": [], "action_sequences": []}
    for rb in rb_list:
        for train_index in rb.train_index:
            train_set["image_datas"].append(rb.obses[train_index])
            train_set["proprioception_datas"].append(rb.proes[train_index])
            train_set["action_sequences"].append(rb.actions[train_index: train_index + args.context_length])
        for valid_index in rb.valid_index:
            valid_set["image_datas"].append(rb.obses[valid_index])
            valid_set["proprioception_datas"].append(rb.proes[valid_index])
            valid_set["action_sequences"].append(rb.actions[valid_index: valid_index + args.context_length])

    return train_set, valid_set


class CustomDataset(Dataset):
    def __init__(self, data, transform):
        self.image_data = data['image_datas']
        self.proprioception_data = data['proprioception_datas']
        self.action_seq = data['action_sequences']

        self.transform = transform

    def __len__(self):
        return len(self.image_data)

    def __getitem__(self, idx):
        # 从数据集中获取一张图片
        input_image = PIL.Image.fromarray(
            self.image_data[idx].transpose(1, 2, 0).astype(np.uint8)
        )  # 转换为 HWC 格式，并转为 uint8 类型
        input_propr = self.proprioception_data[idx]
        pred_act_seq = self.action_seq[idx]

        # 可以在此处进行额外的数据增强或预处理（如归一化、标准化等）
        input_image = self.transform(input_image)

        return input_image, input_propr, pred_act_seq


transform = transforms.Compose([
    # transforms.Resize(256),
    # transforms.CenterCrop(224),
    transforms.ToTensor(),
    # transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
])

if __name__ == "__main__":
    class Args:
        demo_path = "/home/zjb/.maniskill/demos/PickCube-v1/motionplanning/trajectory.rgb.pd_ee_delta_pos.physx_cpu.h5"
        num_queries = 2
        scale = 150  # 每条轨迹中采样的数据样本条数
        train_split = 0.8  # 训/验比是 9:1 且直接在仿真环境中部署做测试
        valid_split = 0.2
        context_length = 10


    args = Args()
    training_demos, test_demos = get_dataset(args)
    dataset = CustomDataset(data=training_demos, transform=transform)
    print(dataset.__getitem__(2))
