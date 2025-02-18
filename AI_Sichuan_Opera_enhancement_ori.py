import cv2
import numpy as np
import paddlehub as hub
from paddlehub.common.logger import logger
import time
import math
import os


class HeadPostEstimation(object):
    """
        头部姿态识别
        """
    NOD_ACTION = 1
    SHAKE_ACTION = 2
    def __init__(self, face_detector=None):
        self.module = hub.Module(name="face_landmark_localization", face_detector_module=face_detector)
        # 头部3D关键点坐标
        self.model_points = np.array([
                                      [6.825897, 6.760612, 4.402142],
                                      [1.330353, 7.122144, 6.903745],
                                      [-1.330353, 7.122144, 6.903745],
                                      [-6.825897, 6.760612, 4.402142],
                                      [5.311432, 5.485328, 3.987654],
                                      [1.789930, 5.393625, 4.413414],
                                      [-1.789930, 5.393625, 4.413414],
                                      [-5.311432, 5.485328, 3.987654],
                                      [2.005628, 1.409845, 6.165652],
                                      [-2.005628, 1.409845, 6.165652],
                                      [2.774015, -2.080775, 5.048531],
                                      [-2.774015, -2.080775, 5.048531],
                                      [0.000000, -3.116408, 6.097667],
                                      [0.000000, -7.415691, 4.070434],
                                      [-7.308957, 0.913869, 0.000000],
                                      [7.308957, 0.913869, 0.000000],
                                      [0.746313,0.348381,6.263227],
                                      [0.000000,0.000000,6.763430],
                                      [-0.746313,0.348381,6.263227],
                                      ], dtype='float')
            
        # 点头动作index是0， 摇头动作index是1
        # 当连续30帧上下点头动作幅度超过5度时，认为发生了点头动作
        # 当连续30帧上下点头动作幅度超过15度时，认为发生了摇头动作，由于摇头动作较为敏感，故所需幅度更大
        self._index_action = {0:'nod', 1:'shake'}
        self._frame_window_size = 15
        self._pose_threshold = {0: 10/180 * math.pi,
          1: 25/180 * math.pi}
        # 头部3D投影点
        self.reprojectsrc = np.float32([
                                      [10.0, 10.0, 10.0],
                                      [10.0, 10.0, -10.0],
                                      [10.0, -10.0, -10.0],
                                      [10.0, -10.0, 10.0],
                                      [-10.0, 10.0, 10.0],
                                      [-10.0, 10.0, -10.0],
                                      [-10.0, -10.0, -10.0],
                                      [-10.0, -10.0, 10.0]])
        # 头部3D投影点连线
        self.line_pairs = [
                         [0, 1], [1, 2], [2, 3], [3, 0],
                         [4, 5], [5, 6], [6, 7], [7, 4],
                         [0, 4], [1, 5], [2, 6], [3, 7]
                         ]

        self.masks = [
            cv2.imread('mask_1.png', -1),
            cv2.imread('mask_2.png', -1),
            cv2.imread('mask_3.png', -1),
            cv2.imread('mask_4.png', -1)
        ]
        self.index = 0

    @property
    def frame_window_size(self):
        return self._frame_window_size
    
    @frame_window_size.setter
    def frame_window_size(self, value):
        assert isinstance(value, int)
        self._frame_window_size = value
    
    @property
    def pose_threshold(self):
        return self._pose_threshold
    
    @pose_threshold.setter
    def pose_threshold(self, dict_value):
        assert list(dict_value.keys()) == [0,1,2]
        self._pose_threshold = dict_value
    
    def get_face_landmark(self, image):
        """
        预测人脸的68个关键点坐标
        images(ndarray): 单张图片的像素数据
        """
        try:
            res = self.module.keypoint_detection(images=[image])
            return True, res[0]['data'][0]
        except Exception as e:
            logger.error("Get face landmark localization failed! Exception: %s " % e)
            return False, None

    def get_image_points_from_landmark(self, face_landmark):
        """
        从face_landmark_localization的检测结果抽取姿态估计需要的点坐标
        """
        image_points = np.array([
                                 face_landmark[17], face_landmark[21],
                                 face_landmark[22], face_landmark[26],
                                 face_landmark[36], face_landmark[39],
                                 face_landmark[42], face_landmark[45],
                                 face_landmark[31], face_landmark[35],
                                 face_landmark[48], face_landmark[54],
                                 face_landmark[57], face_landmark[8],
                                 face_landmark[14], face_landmark[2],
                                 face_landmark[32], face_landmark[33],
                                 face_landmark[34],
                                 ], dtype='float')
        return image_points
        
    def caculate_pose_vector(self, image_points):
        """
        获取旋转向量和平移向量
        """
        # 相机视角
        center = (self.img_size[1]/2, self.img_size[0]/2)
        focal_length = center[0] / np.tan(60/ 2 * np.pi / 180)
        camera_matrix = np.array([
                                  [focal_length, 0, center[0]],
                                  [0, focal_length, center[1]],
                                  [0, 0, 1]],
                                 dtype = "float")
                                 # 假设没有畸变
        dist_coeffs = np.zeros((4,1))
                                 
        success, rotation_vector, translation_vector= cv2.solvePnP(self.model_points,
                                                                image_points,
                                                                camera_matrix,
                                                                dist_coeffs)

        reprojectdst, _ = cv2.projectPoints(self.reprojectsrc, rotation_vector, translation_vector, camera_matrix, dist_coeffs)
                         
        return success, rotation_vector, translation_vector, camera_matrix, dist_coeffs, reprojectdst

    def caculate_euler_angle(self, rotation_vector, translation_vector):
        """
        将旋转向量转换为欧拉角
        """
        rvec_matrix = cv2.Rodrigues(rotation_vector)[0]
        proj_matrix = np.hstack((rvec_matrix, translation_vector))
        euler_angles = cv2.decomposeProjectionMatrix(proj_matrix)[6]
        pitch, yaw, roll = [math.radians(_) for _ in euler_angles]
        return pitch, yaw, roll

        
    def classify_pose_in_euler_angles(self, video, poses=1):
        """
        根据欧拉角分类头部姿态(点头nod/摇头shake)
        video 表示不断产生图片的生成器
        pose=1 表示识别点头动作
        pose=2 表示识别摇头动作
        pose=3 表示识别点头和摇头动作
        """
        frames_euler = []
        index_action ={0:[self.NOD_ACTION], 1:[self.SHAKE_ACTION]}
        
        for index, img in enumerate(video(), start=1):
            self.img_size = img.shape
            
            success, face_landmark = self.get_face_landmark(img)
            
            for i, action in enumerate(index_action):
                if i == 0:
                    index_action[action].append((20, int(self.img_size[0]/2 + 110)))
                elif i == 1:
                    index_action[action].append((120, int(self.img_size[0]/2 + 110)))
        
            if not success:
                logger.info("Get face landmark localization failed! Please check your image!")
                continue

            image_points = self.get_image_points_from_landmark(face_landmark)
            success, rotation_vector, translation_vector, camera_matrix, dist_coeffs, reprojectdst = self.caculate_pose_vector(image_points)

            if not success:
                logger.info("Get rotation and translation vectors failed!")
                continue
        
            # 计算头部欧拉角
            pitch, yaw, roll = self.caculate_euler_angle(rotation_vector, translation_vector)
            frames_euler.append([index, img, pitch, yaw, roll])

            # 转换成摄像头可显示的格式
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            if len(frames_euler) > self.frame_window_size:
                # 比较当前头部动作欧拉角与过去的欧拉角，只有动作幅度幅度超过阈值，则判定发生相应的动作
                # picth值用来判断点头动作
                # yaw值用来判断摇头动作
                current = [pitch, yaw, roll]
                tmp = [abs(pitch), abs(yaw)]
                max_index = tmp.index(max(tmp))
                max_probability_action = index_action[max_index][0]
                for start_idx, start_img, p, y, r in frames_euler[0:int(self.frame_window_size/2)]:
                    start = [p, y, r]
                    if poses & max_probability_action and abs(start[max_index]-current[max_index]) >= self.pose_threshold[max_index]:
                        frames_euler = []
                        # 摇头发生时即可更换脸谱
                        if self._index_action[max_index] == 'shake':
                          self.index += 1
                          self.index %= 4

                        yield {self._index_action[max_index]: [(start_idx, start_img), (index, img)]}
                        break
                else:
                    # 丢弃过时的视频帧
                    frames_euler.pop(0)

            # 检测画面中人脸位置, 并替换为脸谱
            result = face_detector.face_detection(images=[img])
            if result[0]['data']:
                rect_left = int(result[0]['data'][0]['left'])
                rect_right = int(result[0]['data'][0]['right'])
                rect_bottom = int(result[0]['data'][0]['bottom'])
                rect_top = int(result[0]['data'][0]['top'])
                mask = cv2.resize(self.masks[self.index], (rect_right - rect_left, rect_bottom - rect_top))
                index = mask[:,:,3] != 0
                index = np.repeat(index[:,:,np.newaxis], axis=2, repeats=3)
                img_rgb[rect_top:rect_bottom, rect_left:rect_right,:][index] = mask[:,:,:3][index]
            
            # 本地显示预测视频框，AIStudio不支持显示视频框
            cv2.imshow('Face', img_rgb)
            # 写入预测结果
            video_writer.write(img_rgb)


# 打开摄像头
capture  = cv2.VideoCapture(0) 
fps = capture.get(cv2.CAP_PROP_FPS)
size = (int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
        int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
# 将预测结果写成视频
video_writer = cv2.VideoWriter('result.mp4', cv2.VideoWriter_fourcc(*'mp4v'), fps, size)

def generate_image():
    while True:
        # frame_rgb即视频的一帧数据
        ret, frame_rgb = capture.read() 
        # 按q键即可退出
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

        if frame_rgb is None:
            break
        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        yield frame_bgr
    capture.release()
    video_writer.release()
    cv2.destroyAllWindows()


class MyFaceDetector(object):
    """
    自定义人脸检测器
    基于PaddleHub人脸检测模型ultra_light_fast_generic_face_detector_1mb_640，加强稳定人脸检测框
    """
    def __init__(self):
        self.module = hub.Module(name="ultra_light_fast_generic_face_detector_1mb_640")
        self.alpha = 0.75
        self.start_flag =1
    
    def face_detection(self,images, use_gpu=False, visualization=False):
        # 使用GPU运行，use_gpu=True，并且在运行整个教程代码之前设置CUDA_VISIBLE_DEVICES环境变量
        result = self.module.face_detection(images=images, use_gpu=use_gpu, visualization=visualization)
        if not result[0]['data']:
            return result
        
        face = result[0]['data'][0]
        if self.start_flag == 1:
            
            self.left_s = result[0]['data'][0]['left']
            self.right_s = result[0]['data'][0]['right']
            self.top_s = result[0]['data'][0]['top']
            self.bottom_s = result[0]['data'][0]['bottom']
            
            self.start_flag=0
        else:
            # 加权平均上一帧和当前帧人脸检测框位置，以稳定人脸检测框
            self.left_s = self.alpha * self.left_s +  (1-self.alpha) * face['left']
            self.right_s = self.alpha * self.right_s +  (1-self.alpha) * face['right']
            self.top_s = self.alpha * self.top_s +  (1-self.alpha) * face['top']
            self.bottom_s = self.alpha * self.bottom_s + (1-self.alpha) * face['bottom']
        
        result[0]['data'][0]['left'] = self.left_s
        result[0]['data'][0]['right'] = self.right_s
        result[0]['data'][0]['top'] = self.top_s
        result[0]['data'][0]['bottom'] = self.bottom_s
        
        return result

# 定义人脸检测器
face_detector = MyFaceDetector()

head_post = HeadPostEstimation()
# 发生摇头时，实现AI川剧变脸
for res in head_post.classify_pose_in_euler_angles(video=generate_image, poses=HeadPostEstimation.SHAKE_ACTION):
    print("Change Mask, AI Sichuan Opera!")
